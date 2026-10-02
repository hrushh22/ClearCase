"""EVIDENCE COVERAGE + INJURY X-RAY MAP. Deterministic only.

Each important proposition gets a support state from countable components (verified supporting facts,
independent source types, contradictions, open gaps). No percentages, no outcome scores.
"""
from __future__ import annotations

import re

from ..agents.kpi import provider_bills
from .common import REGION_LABEL, REGIONS, issue_key, regions_in, src

STATES = ["well_corroborated", "supported", "limited", "incomplete", "conflicting"]
STATE_LABEL = {"well_corroborated": "Well corroborated", "supported": "Supported", "limited": "Limited support",
               "incomplete": "Incomplete", "conflicting": "Conflicting evidence"}


def support_state(facts: list[dict], contradictions: int, gaps: int) -> tuple[str, dict]:
    verified = [f for f in facts if f.get("verify_status") == "supported"]
    partial = [f for f in facts if f.get("verify_status") in ("partial", "quote_ok")]
    types = sorted({f["source_type"] for f in verified})
    docs = len({f["source_id"] for f in verified if f["source_type"] == "document"})
    comp = {"verified_sources": len(verified), "needs_review_sources": len(partial), "independent_source_types": len(types),
            "source_types": types, "documents": docs, "contradictions": contradictions, "open_gaps": gaps}
    if contradictions:
        state = "conflicting"
    elif not verified:
        state = "incomplete" if gaps else "limited"
    elif len(verified) >= 3 and len(types) >= 2 and not gaps:
        state = "well_corroborated"
    elif len(verified) >= 2:
        state = "supported" if not gaps or len(verified) >= 3 else "incomplete"
    else:
        state = "incomplete" if gaps else "limited"
    comp["rule"] = {
        "conflicting": "At least one unresolved contradiction touches this proposition.",
        "well_corroborated": "3+ verified sources from 2+ independent source types, no open gaps.",
        "supported": "2+ verified sources.",
        "limited": "Only one verified source (or none) and no open gap.",
        "incomplete": "Open evidence gap with thin verified support.",
    }[state]
    return state, comp


def _touching(issues: list[dict], fact_ids: set[str], extra=lambda i: False) -> list[dict]:
    return [i for i in issues if set(i.get("related_fact_ids") or []) & fact_ids or extra(i)]


def injury_map(facts: list[dict], issues: list[dict]) -> dict:
    """Body regions from injury/treatment facts only. Nothing is placed without a region word in the text."""
    med = [f for f in facts if f["type"] in ("injury", "treatment")]
    regions: dict[str, dict] = {}
    unmapped = []
    bills = provider_bills(facts)
    for f in med:
        regs = regions_in(f["text"] + " " + (f.get("entity") or ""))
        if not regs:
            if f["type"] == "injury":
                unmapped.append(src(f))
            continue
        for key, side in regs:
            r = regions.setdefault(key, {"key": key, "label": REGION_LABEL[key], "sides": set(), "injuries": [], "treatment": [],
                                         "imaging": [], "providers": set(), "fact_ids": set(), "first_date": None})
            if side:
                r["sides"].add(side)
            r["fact_ids"].add(f["fact_id"])
            item = src(f)
            if re.search(r"\bMRI\b|\bCT\b|x-?ray|imaging|radiolog|EMG|NCV", f["text"]):
                r["imaging"].append(item)
            elif f["type"] == "injury":
                r["injuries"].append(item)
            else:
                r["treatment"].append(item)
            if f.get("entity") and not re.search(r"sapini|patient|client|shoulder|knee|neck|back", f["entity"], re.I):
                r["providers"].add(f["entity"])
            d = f.get("date") or f.get("known_at")
            if d and (not r["first_date"] or d < r["first_date"]):
                r["first_date"] = d
    out = []
    for key, r in regions.items():
        ids = r["fact_ids"]
        rel = _touching(issues, ids, lambda i, k=key: (i.get("region") == k))
        contra = [i for i in rel if i["issue_type"] in ("contradiction", "amount_mismatch")]
        gaps = [i for i in rel if i["issue_type"] not in ("contradiction", "amount_mismatch")]
        provs = sorted(r["providers"])
        billed = [b for b in bills if b["kind"] == "bill" and any(p.split(",")[0].lower()[:8] in b["name"].lower() for p in provs)]
        state, comp = support_state([f for f in facts if f["fact_id"] in ids], len(contra), len(gaps))
        out.append({"key": key, "label": r["label"], "sides": sorted(r["sides"]), "first_date": r["first_date"],
                    "injuries": r["injuries"][:12], "treatment": r["treatment"][:12], "imaging": r["imaging"][:8],
                    "providers": provs[:10], "source_count": len(ids), "contradictions": [i["id"] for i in contra],
                    "gaps": [i["id"] for i in gaps], "state": state, "components": comp,
                    "related_bills": [{"name": b["name"], "amount": b["amount"]} for b in billed],
                    "known_billed_total": round(sum(b["amount"] for b in billed), 2) if billed else None,
                    "billed_note": "Sum of Clio charges from providers who treated this region (a provider may treat several regions)."})
    order = [k for k, _, _ in REGIONS]
    out.sort(key=lambda r: order.index(r["key"]))
    return {"regions": out, "unmapped": unmapped[:20]}


def propositions(facts: list[dict], issues: list[dict], injury: dict, kpis: dict | None) -> list[dict]:
    """The case's key propositions, each with its supporting facts and a deterministic support state."""
    props = []

    def add(pid, title, category, fs, extra_issue=lambda i: False):
        fs = fs[:40]
        ids = {f["fact_id"] for f in fs}
        rel = _touching(issues, ids, extra_issue)
        contra = [i for i in rel if i["issue_type"] in ("contradiction", "amount_mismatch") and i.get("verify_status") != "hidden"]
        gaps = [i for i in rel if i["issue_type"] not in ("contradiction", "amount_mismatch")]
        state, comp = support_state(fs, len(contra), len(gaps))
        ranked = sorted(fs, key=lambda f: (f.get("verify_status") != "supported", f["source_type"] == "custom_field", f["fact_id"]))
        props.append({"id": pid, "title": title, "category": category, "state": state, "state_label": STATE_LABEL[state],
                      "components": comp, "fact_ids": [f["fact_id"] for f in ranked], "evidence": [src(f) for f in ranked[:8]],
                      "contradictions": [i["id"] for i in contra], "gaps": [i["id"] for i in gaps]})

    doi = next((f for f in facts if f["source_type"] == "custom_field" and f.get("date") and re.search(r"incident|accident", f["text"], re.I)), None)
    inc = [f for f in facts if re.search(r"accident|incident|collision|sideswip|crash|struck|contacted his", f["text"], re.I)
           and f["type"] in ("client_event", "filing", "other", "risk", "injury")] + ([doi] if doi else [])
    add("p_incident", f"The incident occurred{' on ' + doi['date'] if doi else ''}", "incident", inc,
        lambda i: i.get("kind") == "date")
    for r in injury["regions"]:
        sides = "/".join(r["sides"])
        region_ids = set(_ids_for_region(facts, r["key"]))
        add(f"p_injury_{r['key']}", f"Injury: {(sides + ' ') if sides else ''}{r['label'].lower()}", "injury",
            [f for f in facts if f["fact_id"] in region_ids], lambda i, k=r["key"]: i.get("region") == k)
    add("p_treatment", "Treatment chronology is documented", "treatment", [f for f in facts if f["type"] == "treatment"],
        lambda i: i["issue_type"] == "timeline_gap" or i.get("kind") in ("records", "procedure", "chronology"))
    spec = (kpis or {}).get("specials", {}).get("value")
    add("p_damages", f"Medical specials{(' of $' + format(spec, ',.0f')) if spec else ''}", "damages",
        [f for f in facts if f["type"] in ("bill", "lien", "payment")], lambda i: i["issue_type"] == "amount_mismatch" or i.get("kind") in ("bill", "records_for_bill"))
    cov = (kpis or {}).get("coverage", {})
    add("p_coverage", f"Coverage: {cov.get('headline') or 'as stated in the file'}", "coverage",
        [f for f in facts if f["type"] == "coverage"], lambda i: i.get("kind") == "coverage")
    add("p_liability", "Facts bearing on liability", "liability",
        [f for f in facts if re.search(r"liabilit|scope of employment|fault|negligen|on duty|witness|police report|mechanism", f["text"], re.I)],
        lambda i: i.get("kind") in ("flagged", "semantic"))
    return props


def _ids_for_region(facts, key):
    return [f["fact_id"] for f in facts if f["type"] in ("injury", "treatment") and any(k == key for k, _ in regions_in(f["text"] + " " + (f.get("entity") or "")))]


def proposition_key(pid: str) -> str:
    return issue_key("prop", pid)
