"""One door to every LLM: `complete_json(task, prompt, schema, images=None)`.

Routing (free tiers only):
  vision / page understanding        -> Gemini (newest Flash the key can see)
  extraction / timeline / KPI reading -> Mistral mistral-small-latest
  verifier / priority / stage / share -> Groq openai/gpt-oss-120b
Failover on 429 or provider error: back off, retry, then next provider in Gemini -> Mistral -> Groq order.

Every response is validated with pydantic (one retry with the error), cached by prompt hash
(so the same question is never paid for twice), and logged with token counts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
from collections import deque
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import db
from .config import env

T = TypeVar("T", bound=BaseModel)

ROUTES = {
    "vision": "gemini",
    "extraction": "mistral", "timeline": "mistral", "kpi": "mistral",
    "verifier": "groq", "priority": "groq", "stage": "groq", "share_policy": "groq",
}
FAILOVER = ["gemini", "mistral", "groq"]
KEYS = {"gemini": "GEMINI_API_KEY", "mistral": "MISTRAL_API_KEY", "groq": "GROQ_API_KEY"}
# approximate paid list prices, USD per 1M tokens (input, output), for the per-case cost estimate
PAID_PRICE = {"gemini": (0.30, 2.50), "mistral": (0.10, 0.30), "groq": (0.15, 0.75)}
MIN_INTERVAL = {"gemini": 6.5, "mistral": 1.1, "groq": 2.1}
TPM = {"gemini": 200_000, "mistral": 400_000, "groq": 7_500}
MAX_QUEUE_WAIT = 20.0  # seconds; beyond this a call spills to the next provider


class LLMUnavailable(RuntimeError):
    pass


class _Limiter:
    def __init__(self, provider: str):
        self.provider = provider
        self.last = 0.0
        self.window: deque[tuple[float, int]] = deque()
        self.lock = threading.Lock()

    def eta(self, est_tokens: int) -> float:
        """Rough seconds until a call of this size could start."""
        now = time.time()
        recent = [(t, n) for t, n in self.window if now - t <= 60]
        used = sum(n for _, n in recent)
        gap = max(0.0, MIN_INTERVAL[self.provider] - (now - self.last))
        if recent and used + est_tokens > TPM[self.provider]:
            gap = max(gap, 60 - (now - recent[0][0]))
        return gap

    def wait(self, est_tokens: int) -> None:
        with self.lock:
            while True:
                now = time.time()
                while self.window and now - self.window[0][0] > 60:
                    self.window.popleft()
                used = sum(t for _, t in self.window)
                gap = MIN_INTERVAL[self.provider] - (now - self.last)
                if gap <= 0 and (used + est_tokens <= TPM[self.provider] or not self.window):
                    self.last = now
                    self.window.append((now, est_tokens))
                    return
                time.sleep(max(gap, 0.5))


_limiters = {p: _Limiter(p) for p in FAILOVER}
_gemini_model: str | None = None


def available_providers() -> list[str]:
    return [p for p in FAILOVER if env(KEYS[p])]


def gemini_model() -> str:
    """List models at startup and pick the newest stable `flash` (not lite/image/tts)."""
    global _gemini_model
    if _gemini_model:
        return _gemini_model
    best, best_key = "gemini-2.5-flash", (0.0, 0)
    try:
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                      params={"key": env("GEMINI_API_KEY"), "pageSize": 200}, timeout=20)
        for m in r.json().get("models", []):
            name = m["name"].split("/")[-1]
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if "flash" not in name or re.search(r"lite|image|tts|audio|live|thinking|exp|8b", name):
                continue
            v = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
            if not v:
                continue
            key = (float(v.group(1)), 0 if "preview" in name else 1)
            if key > best_key:
                best, best_key = name, key
    except Exception:
        pass
    _gemini_model = best
    return best


def _schema_prompt(prompt: str, schema: type[BaseModel]) -> str:
    return (f"{prompt}\n\nRespond with ONE JSON object only, no prose, matching this JSON Schema:\n"
            f"{json.dumps(schema.model_json_schema())}")


def _call(provider: str, prompt: str, images: list[bytes] | None) -> tuple[str, int, int, str]:
    key = env(KEYS[provider])
    if provider == "gemini":
        model = gemini_model()
        parts: list[dict] = [{"text": prompt}]
        for img in images or []:
            parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(img).decode()}})
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                       params={"key": key}, timeout=180,
                       json={"contents": [{"parts": parts}],
                             "generationConfig": {"responseMimeType": "application/json", "temperature": 0}})
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(r.text[:300], request=r.request, response=r)
        j = r.json()
        text = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        u = j.get("usageMetadata", {})
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), model
    if images:
        raise LLMUnavailable(f"{provider} is not used for images")
    if provider == "mistral":
        url, model, extra = "https://api.mistral.ai/v1/chat/completions", "mistral-small-latest", {}
    else:
        url, model, extra = "https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-120b", {"reasoning_effort": "low"}
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=180, json={
        "model": model, "temperature": 0, "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}], **extra})
    if r.status_code >= 400:
        raise httpx.HTTPStatusError(r.text[:300], request=r.request, response=r)
    j = r.json()
    u = j.get("usage", {})
    return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0), model


def _log(task, provider, model, pt, ct, ok, error=None):
    with db.tx() as c:
        c.execute("INSERT INTO llm_calls(created_at,task,provider,model,prompt_tokens,completion_tokens,ok,error) "
                  "VALUES(?,?,?,?,?,?,?,?)", (db.now_iso(), task, provider, model, pt, ct, int(ok), error))


def _parse(text: str, schema: type[T]) -> T:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return schema.model_validate_json(text)


def complete_json(task: str, prompt: str, schema: type[T], images: list[bytes] | None = None) -> T:
    full = _schema_prompt(prompt, schema)
    ckey = hashlib.sha256((task + "\x00" + full + "".join(hashlib.sha256(i).hexdigest() for i in images or [])).encode()).hexdigest()
    cached = db.one("SELECT response_json FROM llm_cache WHERE key=?", (ckey,))
    if cached:
        return schema.model_validate_json(cached["response_json"])

    primary = ROUTES.get(task, "mistral")
    order = [primary] + [p for p in FAILOVER if p != primary]
    order = [p for p in order if env(KEYS[p]) and (not images or p == "gemini")]
    if not order:
        raise LLMUnavailable(f"No LLM key configured for task '{task}'. Fill GEMINI_API_KEY / MISTRAL_API_KEY / GROQ_API_KEY in .env.")

    errors = []
    est = len(full) // 3 + 1500
    # spill over: if the routed provider's free-tier budget would stall us, use the next provider now
    if len(order) > 1 and _limiters[order[0]].eta(est) > MAX_QUEUE_WAIT:
        order = order[1:] + order[:1]
    for provider in order:
        attempt_prompt = full
        for attempt in range(4):
            _limiters[provider].wait(len(attempt_prompt) // 3 + 1500)
            try:
                text, pt, ct, model = _call(provider, attempt_prompt, images)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                _log(task, provider, "", 0, 0, False, f"{code}: {str(e)[:200]}")
                errors.append(f"{provider} {code}")
                if code == 429 or code >= 500:
                    time.sleep(min(2 ** attempt * 3, 30))
                    continue
                break
            except (httpx.HTTPError, KeyError, IndexError) as e:
                _log(task, provider, "", 0, 0, False, str(e)[:200])
                errors.append(f"{provider} {type(e).__name__}")
                time.sleep(2)
                continue
            try:
                result = _parse(text, schema)
            except (ValidationError, ValueError) as e:
                _log(task, provider, model, pt, ct, False, f"invalid json: {str(e)[:150]}")
                if attempt == 0:
                    attempt_prompt = full + f"\n\nYour previous answer was invalid: {str(e)[:500]}\nReturn corrected JSON only."
                    continue
                errors.append(f"{provider} invalid-json")
                break
            _log(task, provider, model, pt, ct, True)
            with db.tx() as c:
                c.execute("INSERT OR REPLACE INTO llm_cache(key,response_json,created_at) VALUES(?,?,?)",
                          (ckey, result.model_dump_json(), db.now_iso()))
            return result
    raise LLMUnavailable(f"All providers failed for '{task}': {', '.join(errors)}")


def usage_report() -> dict[str, Any]:
    rows = db.query("SELECT provider, model, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, COUNT(*) n, "
                    "SUM(ok) ok FROM llm_calls GROUP BY provider, model")
    total = 0.0
    for r in rows:
        pin, pout = PAID_PRICE.get(r["provider"], (0, 0))
        r["paid_estimate_usd"] = round(((r["pt"] or 0) * pin + (r["ct"] or 0) * pout) / 1e6, 4)
        total += r["paid_estimate_usd"]
    return {"by_model": rows, "free_tier_cost_usd": 0.0, "paid_estimate_usd": round(total, 4)}
