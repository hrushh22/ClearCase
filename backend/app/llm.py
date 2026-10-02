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
    "stress": "groq",
}
# groq_small = Groq gpt-oss-20b: same key, its own free-tier token bucket; used for bulk work when Mistral is unavailable
FAILOVER = ["gemini", "mistral", "groq_small", "groq"]
KEYS = {"gemini": "GEMINI_API_KEY", "mistral": "MISTRAL_API_KEY", "groq": "GROQ_API_KEY", "groq_small": "GROQ_API_KEY"}
# approximate paid list prices, USD per 1M tokens (input, output), for the per-case cost estimate
PAID_PRICE = {"gemini": (0.30, 2.50), "mistral": (0.10, 0.30), "groq": (0.15, 0.75), "groq_small": (0.075, 0.30)}
MIN_INTERVAL = {"gemini": 6.5, "mistral": 1.1, "groq": 2.1, "groq_small": 2.1}
TPM = {"gemini": 200_000, "mistral": 400_000, "groq": 7_500, "groq_small": 7_500}
MAX_QUEUE_WAIT = 20.0  # seconds; beyond this a call spills to the next provider


class LLMUnavailable(RuntimeError):
    pass


_disabled: set[str] = set()  # providers whose key has no quota (e.g. Mistral plan not activated); skipped for this process


class _Limiter:
    """Reservation-based free-tier limiter: min interval between calls + tokens per rolling minute."""

    def __init__(self, provider: str):
        self.provider = provider
        self.last = 0.0
        self.window: deque[tuple[float, int]] = deque()  # (start time, tokens), may include future reservations

    def _start_time(self, est_tokens: int) -> float:
        now = time.time()
        while self.window and now - self.window[0][0] > 60:
            self.window.popleft()
        t = max(now, self.last + MIN_INTERVAL[self.provider])
        for _ in range(50):
            inside = [(s, n) for s, n in self.window if t - 60 < s <= t]
            if not inside or sum(n for _, n in inside) + est_tokens <= TPM[self.provider]:
                return t
            t = inside[0][0] + 60.01
        return t

    def eta(self, est_tokens: int) -> float:
        return max(0.0, self._start_time(est_tokens) - time.time())

    def reserve(self, est_tokens: int) -> float:
        t = self._start_time(est_tokens)
        self.last = t
        self.window.append((t, est_tokens))
        return t


_pick_lock = threading.Lock()


def _acquire(order: list[str], est_tokens: int, pinned: str | None = None) -> str:
    """Atomically pick the provider that can start soonest (ties go to routing order), reserve it, then wait."""
    with _pick_lock:
        cands = [pinned] if pinned else order
        provider = min(cands, key=lambda p: (round(_limiters[p].eta(est_tokens) / MAX_QUEUE_WAIT), cands.index(p)))
        start = _limiters[provider].reserve(est_tokens)
    delay = start - time.time()
    if delay > 0:
        time.sleep(delay)
    return provider


_limiters = {p: _Limiter(p) for p in FAILOVER}
_gemini_model: str | None = None


def available_providers() -> list[str]:
    return [p for p in FAILOVER if env(KEYS[p]) and p not in _disabled]


def probe() -> dict[str, str]:
    """Cheap quota check before a run, so a key with no quota is known up front (not on the first failure)."""
    out = {}
    for p in [p for p in ("mistral", "groq") if env(KEYS[p]) and p not in _disabled]:
        url = "https://api.mistral.ai/v1/models" if p == "mistral" else "https://api.groq.com/openai/v1/models"
        try:
            if p == "mistral":  # the models list is not rate limited; a 1-token completion shows the real quota
                r = httpx.post("https://api.mistral.ai/v1/chat/completions", timeout=20,
                               headers={"Authorization": f"Bearer {env(KEYS[p])}"},
                               json={"model": "mistral-small-latest", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]})
            else:
                r = httpx.get(url, headers={"Authorization": f"Bearer {env(KEYS[p])}"}, timeout=20)
            if r.status_code == 401 or (r.status_code == 429 and r.headers.get("x-ratelimit-limit-req-minute") == "0"):
                _disabled.add(p)
                if p == "groq":
                    _disabled.add("groq_small")
            out[p] = "disabled" if p in _disabled else "ok"
        except httpx.HTTPError:
            out[p] = "unreachable"
    return out


def bulk_capacity() -> str:
    """'full' when a high-volume provider (Gemini/Mistral) works, else 'limited' (Groq free tier only)."""
    return "full" if any(p in available_providers() for p in ("gemini", "mistral")) else "limited"


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
        model = "openai/gpt-oss-20b" if provider == "groq_small" else "openai/gpt-oss-120b"
        url, extra = "https://api.groq.com/openai/v1/chat/completions", {"reasoning_effort": "low"}
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
    order = [p for p in order if env(KEYS[p]) and p not in _disabled and (not images or p == "gemini")]
    if not order:
        raise LLMUnavailable(f"No LLM key configured for task '{task}'. Fill GEMINI_API_KEY / MISTRAL_API_KEY / GROQ_API_KEY in .env.")

    errors = []
    est = len(full) // 4 + 900  # prompt tokens (~4 chars each) + typical answer
    tried: list[str] = []
    while len(tried) < len(order):
        remaining = [p for p in order if p not in tried and p not in _disabled]
        if not remaining:
            break
        provider = _acquire(remaining, est)  # soonest-available provider; spreads load across free-tier buckets
        tried.append(provider)
        attempt_prompt = full
        for attempt in range(4):
            if attempt > 0:
                _acquire([provider], len(attempt_prompt) // 4 + 900, pinned=provider)
            try:
                text, pt, ct, model = _call(provider, attempt_prompt, images)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                _log(task, provider, "", 0, 0, False, f"{code}: {str(e)[:200]}")
                errors.append(f"{provider} {code}")
                if code == 429 and e.response.headers.get("x-ratelimit-limit-req-minute") == "0":
                    _disabled.add(provider)  # no quota at all on this key: stop trying it
                    break
                if code == 401:
                    _disabled.add(provider)
                    break
                if code == 400 and "json_validate_failed" in str(e) and attempt == 0:
                    continue  # model produced malformed JSON; one more try
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
