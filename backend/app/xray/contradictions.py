"""CONTRADICTION INSPECTOR.

Deterministic checks first (dates, amounts, limits, sequence). Then one optional, cached LLM call pairs up
facts that conflict in meaning (e.g. "denies prior injuries" vs. a prior injury record). Every result
references fact ids; an LLM pair is only kept if both ids are real, visible facts. Harmless paraphrases and
identical values are never flagged. ClearCase never decides which side is right.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from ..agents.kpi import provider_bills
from ..llm import LLMUnavailable, available_providers, complete_json
from .common import amounts_in, dates_in, issue_key, norm, src

INCIDENT_RX = r"accident|incident|collision|sideswip|crash|date of (?:loss|incident|accident)|\bDOI\b|motor vehicle"
LIABILITY_LAYER_EXCLUDE = r"no-fault|UM/UIM|\bUM\b|\bUIM\b|uninsured|underinsured|basic economic"


def _issue(kind, severity, title, explanation, left: Optional[dict], right: Optional[dict], facts: list[dict], label: str,
           method: str = "rule", suggested: str = "") -> dict:
    ids = [f["fact_id"] for f in facts]
    return {"id": issue_key("contradiction", kind, *sorted(ids)), "issue_type": "contradiction" if kind != "amount" else "amount_mismatch",
            "kind": kind, "severity": severity, "title": title, "explanation": explanation, "label": label,
            "left": src(left) if left else None, "right": src(right) if right else None,
            "related_fact_ids": ids, "evidence_for": [src(f) for f in facts], "evidence_against": [],
            "suggested_action": suggested or "Compare both sources and note which account the file relies on.",
            "method": method, "confidence": 0.9 if method == "rule" else 0.6}


def incident_date(facts: list[dict]) -> Optional[dict]:
    """The incident date as stored in a structured Clio field (never guessed from prose)."""
    for f in facts:
        if f["source_type"] == "custom_field" and f.get("date") and re.search(r"incident|accident|loss", f["text"], re.I):
            return f
    return None


def date_conflicts(facts: list[dict], doi: Optional[dict]) -> list[dict]:
    if not doi:
        return []
    out = []
    for f in facts:
        if f is doi:
            continue
        q = f["quote"] or ""
        m = re.search(INCIDENT_RX, q, re.I)
        if not m:
            continue
        # a date written right next to the incident words, not any date in the sentence
        near = q[max(0, m.start() - 45):m.end() + 45]
        for d in dates_in(near):
            if d != doi["date"] and abs(int(d[:4]) - int(doi["date"][:4])) <= 2 and not re.search(r"prior|previous|before", near, re.I):
                out.append(_issue("date", "high", "Incident date differs between sources",
                                  f"The Clio incident field says {doi['date']}; this source gives {d}.", doi, f, [doi, f], "Different incident date"))
                break
    return out


def amount_conflicts(facts: list[dict]) -> list[dict]:
    """Clio charge totals per provider vs. totals stated in notes/emails for the same provider."""
    out = []
    for b in provider_bills(facts):
        if b["kind"] != "bill" or b.get("basis") != "Clio charge entries":
            continue
        total = b["amount"]
        key = norm(b["name"])[:10]
        anchor = next((f for f in facts if f["fact_id"] == (b["sources"][0] or {}).get("fact_id")), None)
        for f in facts:
            if f["type"] != "bill" or f["source_type"] not in ("note", "communication") or not f.get("amount"):
                continue
            if not f.get("entity") or (key not in norm(f["entity"]) and norm(f["entity"])[:10] not in norm(b["name"])):
                continue
            a = float(f["amount"])
            if a >= 0.3 * total and abs(a - total) > max(1.0, 0.01 * total):
                out.append(_issue("amount", "medium", f"{b['name']}: billed amount differs",
                                  f"Clio charge entries total ${total:,.2f}; this source states ${a:,.2f}. One may be out of date.",
                                  anchor or f, f, [x for x in (anchor, f) if x], "Different amount",
                                  suggested=f"Request an updated itemized ledger from {b['name']}."))
    return out


def limit_conflicts(facts: list[dict]) -> list[dict]:
    """Different per-person liability limits stated for the adverse party."""
    lim = []
    for f in facts:
        if f["type"] != "coverage" or re.search(LIABILITY_LAYER_EXCLUDE, f["quote"] or "", re.I):
            continue
        if re.search(r"per person|bodily injury|liability", f["quote"] or "", re.I) and amounts_in(f["quote"]):
            lim.append((amounts_in(f["quote"])[0], f))
    out, seen = [], set()
    for a, f in lim:
        for b, g in lim:
            if a < b and (a, b) not in seen:
                seen.add((a, b))
                out.append(_issue("coverage", "high", "Liability limit stated differently",
                                  f"One source states ${a:,.0f} per person, another ${b:,.0f}.", f, g, [f, g], "Different limit"))
    return out


def lien_conflicts(facts: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for f in facts:
        if f["type"] == "lien" and f.get("amount") and f.get("entity"):
            by.setdefault(norm(f["entity"]).replace("newyorkstate", ""), []).append(f)
    out = []
    for fs in by.values():
        vals = sorted({float(f["amount"]) for f in fs})
        if len(vals) > 1:
            lo = next(f for f in fs if float(f["amount"]) == vals[0])
            hi = next(f for f in fs if float(f["amount"]) == vals[-1])
            out.append(_issue("amount", "medium", f"{hi['entity']} lien amount differs",
                              f"Sources state ${vals[0]:,.2f} and ${vals[-1]:,.2f}.", lo, hi, [lo, hi], "Different lien amount",
                              suggested="Ask the lien holder for a current final lien letter."))
    return out


def sequence_conflicts(facts: list[dict], doi: Optional[dict]) -> list[dict]:
    """Injury/treatment explicitly dated before the incident: may be a prior condition. Needs review."""
    if not doi:
        return []
    out = []
    for f in facts:
        if f["type"] in ("injury", "treatment") and f.get("date") and f["date"] < doi["date"] and f["source_type"] not in ("custom_field",):
            out.append({**_issue("sequence", "medium", "Medical entry dated before the incident",
                                 f"Dated {f['date']}, before the {doi['date']} incident. May be a prior condition.", doi, f, [doi, f],
                                 "Predates incident", suggested="Confirm whether this is a prior, unrelated condition."),
                        "issue_type": "timeline_gap"})
    return out


FLAGGED_RX = r"inconsisten|contradict|discrepan|different accounts|three accounts|conflicting|does not match|doesn't match"


STOP = {"the", "of", "a", "an", "and", "in", "on", "to", "by", "his", "her", "is", "are", "exist", "raise", "has", "have", "was", "with"}


SYNONYMS = {"conflicting": "conflict", "inconsistent": "conflict", "contradictory": "conflict", "contradicted": "conflict",
            "different": "conflict", "differing": "conflict", "collision": "accident", "crash": "accident", "incident": "accident",
            "mechanism": "accident", "version": "account", "statement": "account", "stories": "account", "story": "account"}


def _words(t: str) -> set[str]:
    ws = {w.rstrip("s") for w in re.findall(r"[a-z]+", (t or "").lower()) if w not in STOP and len(w) > 2}
    return {SYNONYMS.get(w, SYNONYMS.get(w + "s", w)) for w in ws}


def file_flagged(facts: list[dict]) -> list[dict]:
    """Inconsistencies the file itself records (e.g. a note saying the client gave different accounts).

    The same inconsistency is often restated in several notes; restatements are grouped into one issue
    (word overlap >= 0.35) with every restatement kept as evidence.
    """
    groups: list[list[dict]] = []
    for f in facts:
        if not (re.search(FLAGGED_RX, f["text"] + " " + (f["quote"] or ""), re.I)
                and f["source_type"] in ("note", "communication", "custom_field", "document")):
            continue
        w = _words(f["text"])
        for g in groups:
            gw = _words(g[0]["text"])
            if w and gw and len(w & gw) / len(w | gw) >= 0.35:
                g.append(f)
                break
        else:
            groups.append([f])
    out = []
    for g in groups:
        g.sort(key=lambda f: (f["verify_status"] != "supported", f["type"] != "risk", f["fact_id"]))
        head = g[0]
        expl = "The file itself records this inconsistency" + (f" ({len(g)} entries say so)." if len(g) > 1 else ".")
        issue = _issue("flagged", "high" if any(f["type"] == "risk" for f in g) else "medium", head["text"][:90], expl,
                       head, g[1] if len(g) > 1 else None, g, "Flagged in the file")
        issue["id"] = issue_key("contradiction", "flagged", norm(head["text"])[:40])
        out.append(issue)
    return out


class Pair(BaseModel):
    a: str
    b: str
    label: str
    explanation: str


class Pairs(BaseModel):
    pairs: list[Pair]


PROMPT = """You review a personal-injury case file for statements that CONFLICT with each other.
Return only pairs of facts (by id) that materially contradict: different dates or amounts for the same thing, a denial vs. evidence
of the same thing, incompatible accounts of the same event. Do NOT pair paraphrases, updates that are explained, or facts about different things.
label: <= 5 words. explanation: <= 25 words, neutral, never say which side is right. At most 8 pairs. Empty list if none.
FACTS:
{facts}"""

SEMANTIC_RX = r"prior|previous|denie|deny|account|mechanism|version|history|before the accident|ankle|photograph|witness|scope of employment|on duty"


def semantic_pairs(facts: list[dict]) -> list[dict]:
    if not available_providers():
        return []
    cands = [f for f in facts if f["source_type"] != "custom_field" and
             (f["type"] == "risk" or re.search(SEMANTIC_RX, f["text"] + " " + (f["quote"] or ""), re.I))]
    cands = sorted(cands, key=lambda f: (f["type"] != "risk", f["fact_id"]))[:60]
    if len(cands) < 2:
        return []
    by = {f["fact_id"]: f for f in cands}
    listing = "\n".join(f'- [{f["fact_id"]}] ({f["source_type"]}, {f.get("known_at") or "undated"}) {f["text"][:160]}' for f in cands)
    try:
        r = complete_json("verifier", PROMPT.format(facts=listing), Pairs)
    except LLMUnavailable:
        return []
    out = []
    for p in r.pairs:
        a, b = by.get(p.a), by.get(p.b)
        if not a or not b or a is b or norm(a["text"]) == norm(b["text"]):
            continue  # unknown ids or a paraphrase: dropped
        out.append(_issue("semantic", "medium", p.label[:80], p.explanation[:240], a, b, [a, b], p.label[:40], method="llm"))
    return out


def detect(facts: list[dict], use_llm: bool = True, llm_pairs: list[dict] | None = None) -> list[dict]:
    doi = incident_date(facts)
    issues = date_conflicts(facts, doi) + amount_conflicts(facts) + limit_conflicts(facts) + lien_conflicts(facts) + \
        sequence_conflicts(facts, doi) + file_flagged(facts)
    if llm_pairs is not None:  # time travel: reuse persisted pairs whose facts were known then
        ids = {f["fact_id"] for f in facts}
        issues += [p for p in llm_pairs if all(i in ids for i in p["related_fact_ids"])]
    elif use_llm:
        issues += semantic_pairs(facts)
    seen, out = set(), []
    for i in issues:
        if i["id"] not in seen:
            seen.add(i["id"])
            out.append(i)
    return out
