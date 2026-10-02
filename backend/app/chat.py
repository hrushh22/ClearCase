"""Chat with two separate brains, plus voice transcription.

Attorney chat  - answers only from the case's VERIFIED facts (and X-Ray issues), retrieved per question, and must
                 cite them; citations become clickable sources. Uncited or unknown ids are dropped.
Provider chat  - answers only from the claims the attorney approved and signed for that one link. Nothing else is
                 ever put in the prompt, so nothing else can leak, whatever the question.
Voice          - audio recorded in the browser is transcribed by Groq Whisper (same GROQ_API_KEY).
"""
from __future__ import annotations

import json
import re
from typing import Optional

import httpx
from pydantic import BaseModel

from . import db
from .agents.verifier import VISIBLE
from .config import env, firm_name
from .llm import LLMUnavailable, available_providers, complete_json

MAX_AUDIO_BYTES = 6 * 1024 * 1024  # ~3 minutes of compressed speech
STOP = set("a an the of to in on for and or is are was were be been do does did what when where who why how which with "
           "this that it its at by from as about any there their his her he she they we our you your i me my can could "
           "should would will has have had tell show give case file please".split())


class ChatAnswer(BaseModel):
    answer: str
    citations: list[str] = []


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9$]+", (text or "").lower()) if w not in STOP and len(w) > 1]


def _history_block(history: list[dict]) -> str:
    turns = [f"{'User' if h.get('role') == 'user' else 'Assistant'}: {str(h.get('text', ''))[:400]}" for h in (history or [])[-6:]]
    return "\n".join(turns) or "(none)"


# ------------------------------------------------------------------------- attorney

def _attorney_context(question: str, history: list[dict], k: int = 28) -> list[dict]:
    """Verified facts + X-Ray issues ranked by word overlap with the question (and the last turn, for follow-ups)."""
    facts = db.query(f"SELECT fact_id, type, text, date, amount, entity, source_type, source_id, page, quote, verify_status "
                     f"FROM facts WHERE verify_status IN ({','.join('?' * len(VISIBLE))})", VISIBLE)
    items = [{"kind": "fact", **f} for f in facts]
    try:
        from .xray import service as xray_service
        for i in (xray_service.latest() or {}).get("issues", []):
            ev = (i.get("evidence_for") or [None])[0]
            if ev:
                items.append({"kind": "issue", "fact_id": i["id"], "type": i["issue_type"], "text": f"{i['title']}. {i['explanation']}",
                              "date": None, "entity": i.get("entity"), "source_type": ev["source_type"], "source_id": ev["source_id"],
                              "page": ev.get("page"), "quote": ev.get("quote"), "verify_status": i.get("verify_status")})
    except Exception:
        pass
    q = set(_terms(question)) | set(_terms(" ".join(h.get("text", "") for h in (history or [])[-2:] if h.get("role") == "user")))
    def score(it):
        words = set(_terms(f"{it['text']} {it.get('entity') or ''} {it['type']} {it.get('quote') or ''}"))
        s = len(q & words) * 3 + sum(1 for w in q if any(x.startswith(w) for x in words))
        return s + (1 if it.get("verify_status") == "supported" else 0) + (0.5 if it.get("date") else 0)
    ranked = sorted(items, key=lambda it: (-score(it), it.get("date") or ""))
    top = [it for it in ranked if score(it) > 1][:k]
    return top or ranked[:12]


def _key_items() -> list[dict]:
    """The dashboard's headline values as citable items, each with its real source."""
    from .digest import load_digest
    d = load_digest() or {}
    if not d:
        return []
    out = []

    def add(text, src, kind="dashboard"):
        if src and src.get("source_type") and src.get("source_id"):
            out.append({"kind": kind, "fact_id": src.get("fact_id") or f"k{len(out)}", "type": "summary", "text": text, "date": src.get("date"),
                        "entity": None, "source_type": src["source_type"], "source_id": src["source_id"], "page": src.get("page"),
                        "quote": src.get("quote"), "verify_status": "supported"})

    k, s, c, a, st = d.get("kpis", {}), d.get("snapshot", {}), d.get("contact", {}), d.get("attention", {}), d.get("stage", {})
    first = lambda x: (x.get("sources") or [None])[0]
    add(f"Estimated case value: ${k.get('case_value', {}).get('value') or 0:,.0f}", first(k.get("case_value", {})))
    add(f"Coverage: {k.get('coverage', {}).get('headline')}", first(k.get("coverage", {})))
    add(f"Medical specials to date: ${k.get('specials', {}).get('value') or 0:,.0f}", first(k.get("specials", {})))
    add(f"Firm spend: ${k.get('firm_spend', {}).get('value') or 0:,.2f} across {k.get('firm_spend', {}).get('count')} expense entries", first(k.get("firm_spend", {})))
    if st.get("evidence"):
        add(f"Case stage: {st.get('stage')} (Clio stage {st.get('clio_stage')}); last movement {st.get('last_movement_at')}", st["evidence"][0])
    if c.get("last"):
        add(f"Last real contact with the client: {c['last']['date']} by {c['last'].get('channel')} ({c['last']['direction']}): {c['last']['title']}", c["last"])
    if c.get("last_from_client"):
        add(f"Last time the client reached out: {c['last_from_client']['date']}: {c['last_from_client']['title']}", c["last_from_client"])
    for o in a.get("overdue", [])[:4]:
        add(f"Overdue task (due {o['due']}, {o.get('days_overdue')} days overdue): {o['title']}", o)
    for w in a.get("waiting", [])[:4]:
        add(f"Waiting on {w.get('waiting_on') or 'a third party'}: {w['title']}", w)
    for u in a.get("upcoming", [])[:4]:
        add(f"Coming up {u['due']}: {u['title']}", u)
    if s.get("client", {}).get("name"):
        add(f"Client: {s['client']['name']}; matter {s.get('display_number')}: {s.get('title')}; status {s.get('status')}; "
            f"responsible attorney {s.get('responsible_attorney')}; SOL {s.get('statute_of_limitations')}", s["client"].get("source"))
    return out


ATTORNEY_PROMPT = """You are ClearCase's assistant for the attorney on this personal-injury matter.
Answer the question using ONLY the numbered items below. Be brief (2-5 sentences or a short list),
plain English, specific (names, dates, amounts). After each statement taken from an item, cite it like [3].
Each item is about the person or provider it names. When the question names a person or provider, use ONLY items
that name them; never attach another party's request, bill or detail to them.
If the items do not contain the answer, say "I couldn't find that in the verified case file." Never guess, never give legal advice,
never predict outcomes. Put every item number you cited in "citations" (as strings, e.g. "3").

ITEMS (dashboard values first, then facts and X-Ray issues relevant to the question):
{items}

CONVERSATION SO FAR:
{history}

QUESTION: {question}"""


def attorney_chat(question: str, history: list[dict] | None = None) -> dict:
    question = (question or "").strip()[:800]
    if not question:
        return {"answer": "Ask me anything about this case.", "citations": []}
    ctx = _key_items() + _attorney_context(question, history or [], k=24)
    listing = "\n".join(f"[{n}] ({it['source_type']}{' p.' + str(it['page']) if it.get('page') else ''}, {it.get('date') or 'undated'}"
                        f"{', needs review' if it.get('verify_status') != 'supported' else ''}) {it['text'][:240]}"
                        for n, it in enumerate(ctx, 1))
    if not available_providers():
        return {"answer": "The AI assistant is offline (no working LLM key). The dashboard still shows every verified fact.",
                "citations": [], "offline": True}
    try:
        r = complete_json("chat", ATTORNEY_PROMPT.format(items=listing, history=_history_block(history or []),
                                                         question=question), ChatAnswer)
    except LLMUnavailable:
        return {"answer": "The AI assistant is busy right now (free-tier limit). Please try again in a minute.", "citations": [], "offline": True}
    cites = []
    for c in r.citations + re.findall(r"\[(\d+)\]", r.answer):
        idx = int(re.sub(r"\D", "", str(c)) or 0)
        if 1 <= idx <= len(ctx) and idx not in [x["n"] for x in cites]:
            it = ctx[idx - 1]
            cites.append({"n": idx, "fact_id": it["fact_id"], "source_type": it["source_type"], "source_id": it["source_id"],
                          "page": it.get("page"), "quote": it.get("quote"), "text": it["text"][:160], "kind": it["kind"]})
    answer = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if any(c["n"] == int(m.group(1)) for c in cites) else "", r.answer).strip()
    return {"answer": answer, "citations": cites}


# ------------------------------------------------------------------------- provider

PROVIDER_PROMPT = """You are the case-status assistant on a page that {firm} shared with {provider}, a medical provider treating their client.
Answer ONLY from the numbered items below; they are everything the firm chose to share. Be brief and polite (1-4 sentences),
cite items like [2], and put their numbers in "citations". If the items do not answer the question, reply:
"I can't share that here. Please contact {firm} directly." Never speculate about case strategy, value, settlement or other providers.

SHARED ITEMS:
{items}

CONVERSATION SO FAR:
{history}

QUESTION: {question}"""


def provider_chat(token: str, question: str, history: list[dict] | None = None) -> dict:
    from .sharing import _active_claims, _now

    link = db.one("SELECT * FROM share_links WHERE token=?", (token,))
    if not link:
        return {"error": "not_found"}
    if link["revoked"] or link["expires_at"] < _now().isoformat():
        return {"error": "inactive", "answer": "This link is no longer active.", "citations": []}
    question = (question or "").strip()[:600]
    claims = _active_claims(token)  # the allowlist: approved, signed, current claims of THIS link only
    items = [{"id": c["id"], "text": json.loads(c["payload_json"])["claim"], "category": c["category"]} for c in claims]
    if not question:
        return {"answer": "Ask me about the case status, your bills, or what the firm needs from your office.", "citations": []}
    if not available_providers():
        return {"answer": "The assistant is offline right now. Everything shared with you is shown on this page.", "citations": [], "offline": True}
    listing = "\n".join(f"[{n}] {it['text']}" for n, it in enumerate(items, 1)) or "(nothing has been shared)"
    try:
        r = complete_json("chat", PROVIDER_PROMPT.format(firm=firm_name(), provider=link["provider_name"], items=listing,
                                                         history=_history_block(history or []), question=question), ChatAnswer)
    except LLMUnavailable:
        return {"answer": "The assistant is busy right now. Please try again in a minute.", "citations": [], "offline": True}
    cites = []
    for c in r.citations + re.findall(r"\[(\d+)\]", r.answer):
        idx = int(re.sub(r"\D", "", str(c)) or 0)
        if 1 <= idx <= len(items) and idx not in [x["n"] for x in cites]:
            cites.append({"n": idx, "claim_id": items[idx - 1]["id"], "text": items[idx - 1]["text"]})
    return {"answer": r.answer.strip(), "citations": cites}


# ------------------------------------------------------------------------- voice

def transcribe(audio: bytes, mime: str) -> dict:
    """Speech to text with Groq Whisper. Audio is sent to Groq once and not stored by ClearCase."""
    if not audio:
        raise ValueError("No audio received")
    if len(audio) > MAX_AUDIO_BYTES:
        raise OverflowError("Recording too long")
    key = env("GROQ_API_KEY")
    if not key:
        raise LookupError("Voice needs GROQ_API_KEY")
    ext = "webm" if "webm" in mime else "ogg" if "ogg" in mime else "mp4" if ("mp4" in mime or "m4a" in mime) else "wav" if "wav" in mime else "webm"
    r = httpx.post("https://api.groq.com/openai/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"}, timeout=60,
                   data={"model": "whisper-large-v3-turbo", "response_format": "json", "language": "en"},
                   files={"file": (f"speech.{ext}", audio, mime or "audio/webm")})
    if r.status_code >= 400:
        raise RuntimeError(f"Transcription failed ({r.status_code})")
    with db.tx() as c:
        c.execute("INSERT INTO llm_calls(created_at,task,provider,model,prompt_tokens,completion_tokens,ok,error) VALUES(?,?,?,?,?,?,?,?)",
                  (db.now_iso(), "transcribe", "groq", "whisper-large-v3-turbo", 0, 0, 1, None))
    return {"text": (r.json().get("text") or "").strip()}
