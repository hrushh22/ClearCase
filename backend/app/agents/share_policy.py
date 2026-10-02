"""SHARE-POLICY AGENT: propose what a treating provider may see.

Candidates are built in code from the cached digest and *supported* facts only (a claim the
verifier could not back can never be offered). Groq then proposes share / withhold per claim with
a reason. Share: status and stage changes, that provider's own bills and records, what the firm needs
from them, upcoming visits. Withhold: strategy, valuation, settlement posture, liability problems,
credibility issues, other providers' money. The attorney has the final say in the UI.
"""
from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel

from .. import db
from ..llm import LLMUnavailable, available_providers, complete_json

GENERIC = {"services", "surgical", "orthopaedic", "orthopedic", "offices", "office", "physical", "therapy", "hospital", "advanced",
           "chiropractic", "medical", "center", "group", "health", "associates", "pllc", "york", "street", "imaging"}


def provider_contacts(bundle: dict) -> list[dict]:
    out = []
    contacts = bundle.get("contacts", [])
    company_names = {c.get("name") for c in contacts if c.get("type") == "Company"}
    for c in contacts:
        rel = c.get("relationship") or ""
        # a doctor who works for a provider company is shared through that company, not separately
        works_for_provider = c.get("type") == "Person" and c.get("company") in company_names
        if re.search(r"provider|hospital|treating|physician|clinic|therap|chiropract", rel, re.I) and not works_for_provider:
            people = [p["name"] for p in contacts if p.get("company") and p.get("company") == c.get("name") and p["id"] != c["id"]]
            out.append({"id": c["id"], "name": c["name"], "type": c.get("type"), "relationship": rel, "email": c.get("email"), "people": people,
                        "tokens": [c["name"].split()[-1].lower()] if c.get("type") == "Person" else provider_tokens(c["name"], people)})
    return out


def provider_tokens(name: str, people: list[str]) -> list[str]:
    toks = [t for t in re.findall(r"[a-z]+", name.lower()) if len(t) >= 5 and t not in GENERIC]
    for p in people:
        last = p.split()[-1].lower()
        if len(last) >= 4:
            toks.append(last)
    return toks[:4]


def _slug(name: str) -> str:
    """Stable key part from a name, so a claim keeps its identity across syncs."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())[:24]


def mentions(text: str, tokens: list[str]) -> bool:
    t = (text or "").lower()
    return any(tok in t for tok in tokens)


def source_hash(source_type: str, source_id: str, page: int | None) -> str:
    if source_type == "document":
        row = db.one("SELECT text FROM doc_pages WHERE doc_id=? AND page=?", (source_id, page or 1))
        return hashlib.sha256(((row or {}).get("text") or "").encode()).hexdigest()
    row = db.one("SELECT sha256 FROM sources WHERE source_type=? AND source_id=?", (source_type, source_id))
    return (row or {}).get("sha256") or hashlib.sha256(b"").hexdigest()


def _claim(cid, text, category, src, suggested="share", reason=""):
    return {"id": cid, "text": text, "category": category, "source": src, "suggested": suggested, "reason": reason,
            "source_hash": source_hash(src["source_type"], src["source_id"], src.get("page"))}


def build_candidates(digest: dict, provider: dict) -> list[dict]:
    toks = provider["tokens"]
    snap = digest["snapshot"]
    stage = digest["stage"]
    cands = []
    matter_src = {"source_type": "matter", "source_id": snap["matter_id"], "page": None, "quote": f"Status: {snap['status']}"}
    cands.append(_claim("status", f"The case is {'open and active' if stage.get('alive') else 'no longer active'} (Clio status: {snap['status']}).",
                        "status", matter_src))
    if stage.get("stage") and stage["stage"] != "unknown" and stage.get("evidence"):
        cands.append(_claim("stage", f"Current stage: {stage['stage']}.", "status", stage["evidence"][0]))
    if stage.get("last_movement"):
        lm = stage["last_movement"]
        cands.append(_claim("last_movement", f"Last case activity on {lm['date']}.", "status", lm))
    cov = digest["kpis"]["coverage"]
    if cov.get("sources"):
        cands.append(_claim("coverage", f"Coverage behind the case: {cov['headline']}.", "coverage", cov["sources"][0]))
        cands.append(_claim("coverage_exists", "There is insurance coverage behind this case." if cov.get("value") else
                            "Coverage: " + cov["headline"] + ".", "coverage", cov["sources"][0]))
    for i, b in enumerate(digest["kpis"]["specials"].get("providers", [])):
        if b["kind"] == "bill" and mentions(b["name"], toks) and b.get("sources"):
            cands.append(_claim(f"bill_{_slug(b['name'])}", f"Your office's bill on file with the firm: ${b['amount']:,.2f}.", "bills", b["sources"][0]))
    for i, b in enumerate(digest["kpis"]["specials"].get("providers", [])):
        if not mentions(b["name"], toks) and b.get("sources"):
            cands.append(_claim(f"otherbill_{_slug(b['name'])}", f"{b['name']} {b['kind']}: ${b['amount']:,.2f}.", "other_providers", b["sources"][0]))
            break
    for i, w in enumerate(digest["attention"].get("waiting", [])):
        if mentions((w.get("waiting_on") or "") + " " + w["title"], toks):
            src = {"source_type": w["source_type"], "source_id": w["source_id"], "page": None, "quote": w["title"]}
            cands.append(_claim(f"need_{w['source_id']}", f"The firm needs from your office: {w.get('detail') or w['title']}", "needs", src))
    for i, u in enumerate(digest["attention"].get("upcoming", [])):
        is_visit = re.search(r"treatment|appointment|visit|surgery|arthroscopy|therapy|consult|follow-up", u["title"], re.I) \
            and not re.search(r"\bcall\b|file review|client appointment", u["title"], re.I)
        if u["kind"] == "calendar" and is_visit and mentions(u["title"], toks):
            src = {"source_type": u["source_type"], "source_id": u["source_id"], "page": None, "quote": u["title"]}
            cands.append(_claim(f"visit_{u['source_id']}", f"Patient's next scheduled visit: {u['due']} ({u['title']}).", "treatment", src))
    # supported facts that mention this provider, plus a few strategy facts the agent should hold back
    facts = [f for f in digest["facts"] if f.get("verify_status") == "supported"]
    already = {c["source"].get("fact_id") for c in cands if c.get("source")}
    # clinical and billing facts about this office only; firm expenses and internal tasks are the firm's business
    mine = [f for f in facts if f["type"] in ("treatment", "provider", "bill", "injury", "payment")
            and f["source_type"] not in ("expense", "task", "custom_field") and f["fact_id"] not in already
            and mentions(f["text"] + " " + (f.get("entity") or "") + " " + f["quote"], toks)]
    mine.sort(key=lambda f: f.get("date") or "", reverse=True)
    seen_text = set()
    for f in mine:
        key = re.sub(r"\W", "", f["text"].lower())[:80]
        if key in seen_text:
            continue
        seen_text.add(key)
        cands.append(_claim(f"fact_{f['fact_id']}", f["text"], "provider_facts", f))
        if len(seen_text) >= 10:
            break
    strategy = [f for f in facts if f["type"] in ("risk", "valuation", "offer", "demand")]
    strategy.sort(key=lambda f: f.get("date") or "", reverse=True)
    for f in strategy[:6]:
        cands.append(_claim(f"fact_{f['fact_id']}", f["text"], "strategy", f))
    seen, out = set(), []
    for c in cands:
        if c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    return out


class Proposal(BaseModel):
    id: str
    decision: Literal["share", "withhold"]
    reason: str


class Proposals(BaseModel):
    items: list[Proposal]


PROMPT = """A personal-injury firm is sharing case status with a treating medical provider ({provider}) who treats the client on a lien.
For each candidate claim, propose share or withhold, with a reason (<= 14 words).
SHARE: case status and stage, last activity, that provider's own bills and records, what the firm needs from that office, upcoming visits with that office,
whether coverage exists (attorney may decide on amounts).
WITHHOLD: case strategy, valuation, settlement posture, demands/offers, liability weaknesses, client credibility issues, other providers' bills,
anything confidential that the provider does not need.
CANDIDATES:
{items}"""

RULES = {"status": "share", "treatment": "share", "bills": "share", "needs": "share", "coverage": "share",
         "provider_facts": "share", "strategy": "withhold", "other_providers": "withhold"}


def propose(digest: dict, provider: dict) -> dict:
    cands = build_candidates(digest, provider)
    method = "rules"
    for c in cands:
        c["suggested"] = RULES.get(c["category"], "withhold")
        c["reason"] = {"strategy": "Case strategy or posture; not needed by a provider.",
                       "other_providers": "Another provider's money; not this office's business."}.get(c["category"], "Relevant to the provider's treatment and billing.")
    if cands and available_providers():
        items = "\n".join(f'- id: {c["id"]} | category: {c["category"]} | {c["text"]}' for c in cands)
        try:
            r = complete_json("share_policy", PROMPT.format(provider=provider["name"], items=items), Proposals)
            by = {p.id: p for p in r.items}
            for c in cands:
                if c["id"] in by:
                    c["suggested"], c["reason"] = by[c["id"]].decision, by[c["id"]].reason
            method = "llm"
        except LLMUnavailable:
            pass
    # hard floor: strategy and other providers' money are never pre-selected, whatever the model says
    for c in cands:
        if c["category"] in ("strategy", "other_providers"):
            c["suggested"] = "withhold"
    return {"provider": provider, "candidates": cands, "method": method}
