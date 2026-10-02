"""TIMELINE + INJURIES AGENTS.

Timeline: dated, verified facts sorted in code. Mistral only picks the milestones and gives each a
short label; every entry keeps its fact's source. Injuries: Mistral groups injury/treatment facts
(mostly from the scanned medical records) by body part, each line citing fact ids with pages.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from ..llm import LLMUnavailable, available_providers, complete_json

CATEGORY = {"injury": "medical", "treatment": "medical", "provider": "medical", "bill": "money", "lien": "money", "payment": "money",
            "expense": "money", "coverage": "insurance", "demand": "negotiation", "offer": "negotiation", "deadline": "deadline",
            "filing": "court", "contact": "client", "client_event": "client", "valuation": "money", "risk": "risk", "other": "other"}


def _src(f):
    return {"fact_id": f["fact_id"], "source_type": f["source_type"], "source_id": f["source_id"], "page": f.get("page"),
            "quote": f["quote"], "date": f.get("date")}


class Milestone(BaseModel):
    fact_id: str
    label: str


class Milestones(BaseModel):
    milestones: list[Milestone]


MS_PROMPT = """Pick the 18-25 milestones that tell the story of this personal-injury case (accident, first treatment, surgeries,
records, coverage findings, demand, offers, suit, discovery, IMEs, experts, liens, recent blockers). Label each in <= 8 words.
Use only fact ids from this list.
FACTS:
{facts}"""


def build_timeline(facts: list[dict]) -> dict:
    dated = sorted([f for f in facts if f.get("date")], key=lambda f: (f["date"], f["fact_id"]))
    events = [{**_src(f), "text": f["text"], "type": f["type"], "category": CATEGORY.get(f["type"], "other"),
               "amount": f.get("amount"), "entity": f.get("entity"), "verify_status": f.get("verify_status")} for f in dated]
    milestones: dict[str, str] = {}
    method = "code"
    if dated and available_providers():
        cands = [f for f in dated if f["type"] not in ("expense",)]
        listing = "\n".join(f'- [{f["fact_id"]}] {f["date"]} ({f["type"]}) {f["text"][:140]}' for f in cands[-260:])
        try:
            r = complete_json("timeline", MS_PROMPT.format(facts=listing), Milestones)
            ids = {f["fact_id"] for f in cands}
            milestones = {m.fact_id: m.label for m in r.milestones if m.fact_id in ids}
            method = "llm"
        except LLMUnavailable:
            pass
    if not milestones:
        keep = ("filing", "demand", "offer", "coverage", "lien", "valuation", "risk")
        seen_day = set()
        for f in dated:
            if f["type"] in keep or (f["type"] == "treatment" and re.search(r"surgery|arthroscopy|IME", f["text"], re.I)):
                if f["date"] not in seen_day:
                    milestones[f["fact_id"]] = f["text"][:60]
                    seen_day.add(f["date"])
    for e in events:
        if e["fact_id"] in milestones:
            e["milestone"] = milestones[e["fact_id"]]
    return {"events": events, "milestone_method": method}


class InjuryLine(BaseModel):
    body_part: str
    finding: str
    treatment: str
    status: Optional[str] = None
    fact_ids: list[str]


class ProviderLine(BaseModel):
    name: str
    role: str
    fact_ids: list[str]


class InjuryRead(BaseModel):
    injuries: list[InjuryLine]
    providers: list[ProviderLine]


INJ_PROMPT = """From these verified facts (many from scanned medical records), summarize the client's injuries by body part and who treated them.
One line per body part: finding (diagnosis / imaging result), treatment so far, status. Cite the fact ids behind each line.
Do not add anything the facts do not say.
FACTS:
{facts}"""


def build_injuries(facts: list[dict]) -> dict:
    med = [f for f in facts if f["type"] in ("injury", "treatment", "provider")]
    med.sort(key=lambda f: (f["source_type"] != "document", f.get("date") or ""))
    by_id = {f["fact_id"]: f for f in med}
    if med and available_providers():
        listing = "\n".join(f'- [{f["fact_id"]}] ({f["source_type"]}{" p." + str(f["page"]) if f.get("page") else ""}) {f["text"][:160]}'
                            for f in med[:220])
        try:
            r = complete_json("kpi", INJ_PROMPT.format(facts=listing), InjuryRead)
            return {"method": "llm",
                    "injuries": [{**i.model_dump(), "sources": [_src(by_id[x]) for x in i.fact_ids if x in by_id]} for i in r.injuries],
                    "providers": [{**p.model_dump(), "sources": [_src(by_id[x]) for x in p.fact_ids if x in by_id]} for p in r.providers]}
        except LLMUnavailable:
            pass
    inj = [f for f in med if f["type"] == "injury"][:25]
    return {"method": "code", "injuries": [{"body_part": "", "finding": f["text"], "treatment": "", "status": None,
                                            "fact_ids": [f["fact_id"]], "sources": [_src(f)]} for f in inj], "providers": []}
