"""STAGE AGENT: where is the case, judged from evidence, with sources.

Provider-facing tracker stages: Treatment -> Demand sent -> Negotiation -> Litigation -> Settlement.
The LLM (Groq) classifies from dated evidence; a code classifier is the fallback and the cross-check.
Clio's own matter stage is shown alongside, never silently substituted. Weak evidence -> "unknown".
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from ..llm import LLMUnavailable, available_providers, complete_json

TRACKER = ["Treatment", "Demand sent", "Negotiation", "Litigation", "Settlement"]
EVIDENCE_RX = [
    ("Settlement", r"settle(d|ment) (reached|agreed)|release (signed|executed)|stipulation of discontinuance|case (settled|closed)"),
    ("Litigation", r"summons|complaint|verified answer|bill of particulars|discovery|deposition|compliance conference|subpoena|index no|IME|expert exchange|note of issue"),
    ("Negotiation", r"offer|negotiat|counter"),
    ("Demand sent", r"demand (package|letter)|demand .*served|served .*demand"),
    ("Treatment", r"treat|therapy|surgery|chiropractic|physical therapy|arthroscopy"),
]


class StageRead(BaseModel):
    stage: Literal["Treatment", "Demand sent", "Negotiation", "Litigation", "Settlement", "unknown"]
    alive: bool
    confidence: float
    reason: str
    evidence_fact_ids: list[str]


PROMPT = """Classify where this personal-injury case stands, using only the dated evidence below.
Stages in order: Treatment, Demand sent, Negotiation, Litigation, Settlement. A case can still be treating while in litigation;
pick the furthest stage the evidence proves. Return "unknown" if the evidence is weak. alive=false only if the file shows it settled, was dismissed or closed.
Clio's own stage field says: {clio_stage}.
EVIDENCE (newest first):
{evidence}"""


def _src(f):
    return {"fact_id": f["fact_id"], "source_type": f["source_type"], "source_id": f["source_id"], "page": f.get("page"),
            "quote": f["quote"], "date": f.get("date")}


def code_stage(facts: list[dict]) -> tuple[str, list[dict]]:
    for stage, rx in EVIDENCE_RX:
        ev = [f for f in facts if re.search(rx, f["text"] + " " + f["quote"], re.I) and f["type"] not in ("deadline",)]
        if len(ev) >= (1 if stage != "Treatment" else 1):
            return stage, sorted(ev, key=lambda f: f.get("date") or "", reverse=True)
    return "unknown", []


def classify(facts: list[dict], clio_stage: str | None, matter_status: str | None) -> dict:
    dated = sorted([f for f in facts if f.get("date")], key=lambda f: f["date"], reverse=True)
    code, code_ev = code_stage(dated)
    result = {"stage": code, "method": "code", "reason": "Keyword evidence in dated records", "evidence": [_src(f) for f in code_ev[:6]],
              "confidence": 0.6 if code != "unknown" else 0.0}
    candidates = [f for f in dated if f["type"] in ("filing", "demand", "offer", "deadline", "treatment", "payment", "other", "client_event")][:60]
    if candidates and available_providers():
        ev = "\n".join(f'- [{f["fact_id"]}] {f["date"]} ({f["type"]}) {f["text"]}' for f in candidates)
        try:
            r = complete_json("stage", PROMPT.format(clio_stage=clio_stage or "not set", evidence=ev), StageRead)
            by_id = {f["fact_id"]: f for f in candidates}
            evidence = [by_id[i] for i in r.evidence_fact_ids if i in by_id]
            if r.stage != "unknown" and evidence:
                result = {"stage": r.stage, "method": "llm", "reason": r.reason, "evidence": [_src(f) for f in evidence[:6]],
                          "confidence": r.confidence, "alive_llm": r.alive}
        except LLMUnavailable:
            pass
    status = (matter_status or "").lower()
    result["alive"] = status not in ("closed",) and result["stage"] != "Settlement"
    result["alive_basis"] = f"Clio matter status: {matter_status or 'unknown'}"
    result["clio_stage"] = clio_stage
    result["tracker"] = TRACKER
    result["index"] = TRACKER.index(result["stage"]) if result["stage"] in TRACKER else -1
    movement = [f for f in dated if f["type"] in ("filing", "demand", "offer", "payment") or
                (f["source_type"] == "document")]
    result["last_movement"] = _src(movement[0]) if movement else (_src(dated[0]) if dated else None)
    result["last_movement_at"] = result["last_movement"]["date"] if result["last_movement"] else None
    return result
