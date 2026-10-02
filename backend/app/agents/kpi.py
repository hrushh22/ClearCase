"""KPI AGENT: case value, coverage, medical specials, firm spend.

Sums are code. The LLM (Mistral) only *reads* coverage facts and writes a headline; any dollar
figure in that headline must appear in a cited quote or the headline is replaced by a code-built one.
Coverage never invents a number: if nothing in the file states a limit, it says so.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..llm import LLMUnavailable, available_providers, complete_json


def _src(f: dict) -> dict:
    return {"fact_id": f["fact_id"], "source_type": f["source_type"], "source_id": f["source_id"], "page": f.get("page"),
            "quote": f["quote"], "date": f.get("date")}


def _amounts(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in re.findall(r"\$\s?([0-9][0-9,]*(?:\.\d+)?)", text or "")]


def case_value(facts: list[dict]) -> dict:
    """Custom field first (structured), then the latest valuation fact from notes/documents."""
    cf = [f for f in facts if f["type"] == "valuation" and f["source_type"] == "custom_field" and f["amount"]]
    if cf:
        f = cf[0]
        others = [x for x in facts if x["type"] == "valuation" and x["source_type"] != "custom_field"]
        return {"value": f["amount"], "basis": "Clio custom field", "sources": [_src(f)] + [_src(x) for x in others[:3]]}
    vals = sorted([f for f in facts if f["type"] == "valuation" and (f["amount"] or _amounts(f["quote"]))],
                  key=lambda f: f.get("date") or "", reverse=True)
    if vals:
        f = vals[0]
        return {"value": f["amount"] or max(_amounts(f["quote"])), "basis": "Latest valuation in the file", "sources": [_src(f)]}
    return {"value": None, "basis": "No valuation found in the file", "sources": []}


def medical_specials(facts: list[dict]) -> dict:
    cf = [f for f in facts if f["source_type"] == "custom_field" and f["type"] == "bill" and f["amount"]]
    providers = provider_bills(facts)
    summed = round(sum(p["amount"] for p in providers if p["kind"] == "bill"), 2)
    out = {"value": cf[0]["amount"] if cf else (summed or None),
           "basis": "Clio custom field" if cf else ("Sum of provider bills found in the file" if summed else "No bills found"),
           "sources": [_src(cf[0])] if cf else [], "provider_sum": summed, "providers": providers}
    if cf and summed and abs(cf[0]["amount"] - summed) > 1:
        out["note"] = f"Provider bills found in the file sum to ${summed:,.0f}, the Clio field says ${cf[0]['amount']:,.0f}."
    return out


def provider_bills(facts: list[dict]) -> list[dict]:
    """One amount per provider (bills) and per lien holder (liens). Deterministic.

    Clio charge entries (structured) are authoritative and summed per provider. For payees only
    mentioned in text, the largest stated amount is kept (a bill's total is at least any line item).
    """
    by_key: dict[str, dict] = {}

    def norm(name: str) -> str:
        return re.sub(r"[^a-z]", "", re.sub(r"\b(inc|llc|pllc|pc|p\.c\.|m\.?d\.?|the)\b", "", name.lower()))

    cands = [f for f in facts if f["type"] in ("bill", "lien") and f["amount"] and f.get("entity") and f["source_type"] != "custom_field"]
    cands.sort(key=lambda f: (f["source_type"] != "expense", f.get("date") or ""))  # structured charges first
    for f in cands:
        n = norm(f["entity"])
        # "Medicaid" and "New York State Medicaid" are the same payee: merge when one name contains the other
        key = next((k for k in by_key if k.split(":", 1)[0] == f["type"] and (n in k.split(":", 1)[1] or k.split(":", 1)[1] in n)),
                   f"{f['type']}:{n}")
        cur = by_key.get(key)
        structured = f["source_type"] == "expense"
        if not cur:
            by_key[key] = {"name": f["entity"], "amount": float(f["amount"]), "kind": f["type"], "date": f.get("date"),
                           "sources": [_src(f)], "structured": structured}
            continue
        if cur["structured"]:
            if structured:
                cur["amount"] += float(f["amount"])
            cur["sources"].append(_src(f))
            continue
        if len(f["entity"]) > len(cur["name"]):
            cur["name"] = f["entity"]
        if float(f["amount"]) > cur["amount"]:
            cur["amount"], cur["date"] = float(f["amount"]), f.get("date")
            cur["sources"].insert(0, _src(f))
        else:
            cur["sources"].append(_src(f))
    out = []
    for v in by_key.values():
        v["basis"] = "Clio charge entries" if v.pop("structured") else "Largest amount stated in the file"
        v["amount"] = round(v["amount"], 2)
        out.append(v)
    return sorted(out, key=lambda x: (x["kind"] != "lien", -x["amount"]))


def firm_spend(facts: list[dict]) -> dict:
    exp = [f for f in facts if f["type"] == "expense" and f["source_type"] == "expense"]
    return {"value": round(sum(f["amount"] or 0 for f in exp), 2), "count": len(exp), "basis": "Sum of Clio expense entries",
            "sources": [_src(f) for f in exp]}


class CoverageRead(BaseModel):
    kind: Literal["policy_limit", "self_insured", "mixed", "none_found"]
    headline: str = Field(description="<= 12 words, e.g. '$100,000 per person (driver's policy)'")
    practical_cap: Optional[float] = Field(description="the per-person limit that realistically caps recovery, or null")
    confirmed: bool = Field(description="true only if the file says the limit was confirmed in writing")
    layers: list[str] = Field(description="one short line per coverage layer found (defendant, self-insured authority, UM/UIM, no-fault, liens)")
    fact_ids: list[str]


COVERAGE_PROMPT = """Read these facts from a personal-injury file and describe the insurance coverage behind the case.
Report only what the facts say. If an adverse party is self-insured, say so; never invent a policy limit.
practical_cap is the ADVERSE party's bodily-injury liability limit per person (not the client's own no-fault or UM/UIM).
The headline names whose policy it is (e.g. "$X per person, at-fault driver's policy").
FACTS:
{facts}"""


def coverage(facts: list[dict]) -> dict:
    cov = [f for f in facts if f["type"] in ("coverage", "lien")]
    cov.sort(key=lambda f: (f.get("date") or "0000"), reverse=True)
    quotes_text = " ".join(f["quote"] for f in cov)
    by_id = {f["fact_id"]: f for f in cov}
    if cov and available_providers():
        listing = "\n".join(f'- [{f["fact_id"]}] ({f.get("date") or "undated"}, {f["source_type"]}) {f["text"]} | quote: "{f["quote"]}"'
                            for f in cov[:40])
        try:
            r = complete_json("kpi", COVERAGE_PROMPT.format(facts=listing), CoverageRead)
            cited = [by_id[i] for i in r.fact_ids if i in by_id] or cov[:3]
            cited_amounts = set(_amounts(" ".join(f["quote"] for f in cited)) + _amounts(quotes_text))
            ok = all(a in cited_amounts for a in _amounts(r.headline)) and \
                (r.practical_cap is None or r.practical_cap in cited_amounts)
            # the cap must come from a liability-layer quote, and the headline must not pin it on no-fault / UM
            other_layer = r"no-fault|UM/UIM|\bUM\b|\bUIM\b|uninsured|underinsured|basic economic"
            if ok and r.practical_cap:
                backing = [f for f in cov if r.practical_cap in _amounts(f["quote"])]
                ok = any(not re.search(other_layer, f["quote"], re.I) for f in backing) and \
                    not re.search(other_layer, r.headline, re.I)
            if ok:
                # headline is built in code from checked values; the model's wording can misattribute whose policy it is
                self_ins = any(re.search(r"self[- ]insured", f["quote"] + " " + f["text"], re.I) for f in cov)
                if r.practical_cap:
                    headline = f"${r.practical_cap:,.0f} per person liability limit" + ("; adverse authority self-insured" if self_ins else "")
                else:
                    headline = "Self-insured adverse party; no policy limit found" if self_ins else "No liability limit found in the file"
                return {"kind": r.kind, "headline": headline, "value": r.practical_cap, "confirmed": r.confirmed,
                        "layers": r.layers, "basis": "Read from coverage facts (LLM), amounts checked against quotes",
                        "sources": [_src(f) for f in cited]}
        except LLMUnavailable:
            pass
    return _coverage_code(cov)


def _coverage_code(cov: list[dict]) -> dict:
    """Deterministic read: self-insured flag + the per-person limit stated most recently."""
    self_ins = [f for f in cov if re.search(r"self[- ]insured", f["quote"] + " " + f["text"], re.I)]
    # the adverse party's liability limit; the client's own UM/UIM and no-fault are other layers
    limit_facts = [f for f in cov if re.search(r"per person|liability|bodily injury|\$[0-9,]+\s*/\s*\$", f["quote"], re.I)
                   and _amounts(f["quote"]) and not re.search(r"UM/UIM|uninsured|underinsured|no-fault|basic economic", f["quote"], re.I)]
    limit_facts.sort(key=lambda f: (not re.search(r"defendant|bodily injury|liability", f["quote"], re.I), f["source_type"] == "custom_field"))
    confirmed = any(re.search(r"confirmed(:\s*yes|\s+in writing)", f["quote"] + " " + f["text"], re.I) for f in cov)
    cap = _amounts(limit_facts[0]["quote"])[0] if limit_facts else None
    if cap and self_ins:
        kind, headline = "mixed", f"${cap:,.0f} per person; adverse authority self-insured"
    elif cap:
        kind, headline = "policy_limit", f"${cap:,.0f} per person"
    elif self_ins:
        kind, headline = "self_insured", "Self-insured adverse party; no policy limit found"
    else:
        kind, headline = "none_found", "No coverage information found in the file"
    srcs = (limit_facts[:2] + self_ins[:2]) or cov[:3]
    return {"kind": kind, "headline": headline, "value": cap, "confirmed": confirmed,
            "layers": [f["text"] for f in srcs], "basis": "Read from coverage facts (code)", "sources": [_src(f) for f in srcs]}
