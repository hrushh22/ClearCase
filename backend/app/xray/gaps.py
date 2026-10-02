"""EVIDENCE GAP DETECTOR (deterministic).

Framing is always: "ClearCase could not locate expected supporting evidence in the available case file."
It never claims the evidence does not exist.
"""
from __future__ import annotations

import re
from datetime import date

from ..agents.kpi import provider_bills
from ..agents.share_policy import mentions, provider_contacts
from .common import REGION_LABEL, issue_key, norm, regions_in, src

FRAMING = "ClearCase could not locate expected supporting evidence in the available case file."
ABSENCE_RX = (r"\bno (?:police|accident) report|not (?:yet )?(?:been )?(?:obtained|produced|received|provided|located)|none (?:obtained|produced)|"
              r"\bmissing\b|has not (?:sent|produced|provided)|have not (?:sent|produced)|sent nothing|still no date|no date (?:given|set)|"
              r"unreconciled|not reconciled|outstanding (?:records|authorizations)|awaiting|never (?:produced|obtained)")
RECOMMEND_RX = r"recommend|advised to undergo|candidate for|planned"
DONE_RX = r"performed|underwent|status post|s/p|post-?operative|operative report|completed"
PROCEDURE_RX = r"surgery|arthroscopy|repair|fusion|injection|procedure"


def _gap(kind, severity, title, why, refs: list[dict], suggested: str, entity: str | None = None, step: str | None = None,
         facts: list[dict] | None = None, issue_type: str = "missing_evidence", extra_key: str = "") -> dict:
    ids = [f["fact_id"] for f in facts or [] if f.get("fact_id")]
    return {"id": issue_key("gap", kind, entity or "", extra_key, *sorted(ids)), "issue_type": issue_type, "kind": kind,
            "severity": severity, "title": title, "explanation": f"{FRAMING} {why}", "related_fact_ids": ids,
            "evidence_for": refs, "evidence_against": [], "suggested_action": suggested, "entity": entity, "step": step,
            "method": "rule", "confidence": 0.8}


def provider_gaps(facts, docs, bundle) -> tuple[list[dict], list[dict]]:
    """Per treating provider: records? bill? Also returns the care chain for the Gap Map."""
    bills = {norm(b["name"])[:12]: b for b in provider_bills(facts) if b["kind"] == "bill"}
    out, chain = [], []
    for p in provider_contacts(bundle):
        toks = p["tokens"]
        recs = [d for d in docs if d["doc_type"] == "medical_record" and any(t in d["name"].lower().replace("-", "") for t in toks)]
        if not recs:  # e.g. a surgeon whose notes sit inside his practice's records: found via facts read from those documents
            doc_ids = {f["source_id"] for f in facts if f["source_type"] == "document" and mentions(f["text"] + " " + (f["quote"] or ""), toks)}
            recs = [d for d in docs if d["id"] in doc_ids and d["doc_type"] == "medical_record"]
        bill_docs = [d for d in docs if d["doc_type"] == "bill" and any(t in d["name"].lower().replace("-", "") for t in toks)]
        charge = next((b for k, b in bills.items() if any(t in k for t in toks) or mentions(b["name"], toks)), None)
        refs = [f for f in facts if mentions(f["text"] + " " + (f.get("entity") or ""), toks)]
        dates = [f["known_at"] for f in refs if f.get("known_at")] + [(d["received_at"] or "")[:10] for d in recs + bill_docs if d["received_at"]]
        if charge and charge.get("date"):
            dates.append(charge["date"])
        first = min(dates) if dates else None
        step = {"name": p["name"], "role": p["relationship"], "first_date": first, "records": [d["id"] for d in recs],
                "bills": [d["id"] for d in bill_docs], "charges": charge["amount"] if charge else None, "mentions": len(refs), "issues": []}
        if not recs and len(refs) >= 2:
            g = _gap("records", "medium", f"No treatment records from {p['name']}",
                     f"{p['name']} is referenced {len(refs)} times but no records document from this provider is in the file.",
                     [src(f) for f in refs[:4]], f"Request complete treatment records from {p['name']}.", p["name"], p["name"], refs[:4])
            out.append(g); step["issues"].append(g["id"])
        if (charge or bill_docs) and not recs and len(refs) < 2:
            g = _gap("records_for_bill", "medium", f"Bill without records: {p['name']}",
                     f"A bill or charge from {p['name']} exists but no matching treatment record was found.",
                     [src(f) for f in refs[:2]], f"Request treatment records supporting the {p['name']} bill.", p["name"], p["name"], refs[:2])
            out.append(g); step["issues"].append(g["id"])
        if recs and not charge and not bill_docs and p.get("type") != "Person":  # individual doctors bill through their practice
            g = _gap("bill", "low", f"Records without a bill: {p['name']}",
                     f"Treatment records from {p['name']} are in the file but no bill or charge entry was found.",
                     [{"source_type": "document", "source_id": recs[0]["id"], "page": 1, "quote": None, "text": recs[0]["name"]}],
                     f"Request an itemized bill from {p['name']}.", p["name"], p["name"], [])
            out.append(g); step["issues"].append(g["id"])
        chain.append(step)
    chain.sort(key=lambda s: s["first_date"] or "9999")
    return out, chain


def imaging_gap(facts, docs) -> list[dict]:
    ref = [f for f in facts if re.search(r"\bMRI\b|\bCT\b|x-?ray|imaging stud|radiolog", f["text"] + " " + (f["quote"] or ""))]
    has = [d for d in docs if re.search(r"radiolog|imaging|mri", d["name"], re.I)]
    if len(ref) >= 2 and not has:
        return [_gap("imaging", "medium", "Imaging referenced, no imaging report", f"{len(ref)} entries mention imaging studies.",
                     [src(f) for f in ref[:4]], "Request the radiology reports and films.", None, "Imaging", ref[:4])]
    return []


def pending_procedures(facts) -> list[dict]:
    """A recommended procedure with no later record that it was performed or scheduled (same body part and side)."""
    out, seen = [], set()
    recs = [f for f in facts if re.search(RECOMMEND_RX, f["text"], re.I) and re.search(PROCEDURE_RX, f["text"], re.I)]
    for r in recs:
        regs = regions_in(r["text"])
        if not regs:
            continue
        reg, side = regs[0]
        key = (reg, side)
        if key in seen:
            continue
        done = [f for f in facts if f is not r and re.search(DONE_RX, f["text"], re.I) and re.search(PROCEDURE_RX, f["text"], re.I)
                and (reg, side) in regions_in(f["text"]) and (f.get("known_at") or "") >= (r.get("known_at") or "")]
        if done:
            continue
        seen.add(key)
        related = [f for f in recs if (reg, side) in regions_in(f["text"])]
        label = f"{side + ' ' if side else ''}{REGION_LABEL[reg].split(' /')[0].lower()}"
        if side is None and any(k[0] == reg and k[1] for k in seen | {x for f in recs for x in regions_in(f["text"])}):
            continue  # a side-less mention of the same recommendation is not a separate gap
        out.append(_gap("procedure", "high", f"Recommended {label} procedure: no record it was scheduled or performed",
                        f"{len(related)} entries recommend it; no later entry documents a date or an operative report.",
                        [src(f) for f in related[:5]], "Confirm the surgical date with the treating surgeon's office, or document why it is not proceeding.",
                        None, f"{label.capitalize()} procedure ?", related[:5], issue_type="dependency", extra_key=label))
    return out


def stated_absences(facts) -> list[dict]:
    """Material the file itself says is missing or outstanding."""
    out, seen = [], set()
    for f in facts:
        hay = f["text"] + " " + (f["quote"] or "")
        if f["source_type"] in ("note", "communication", "custom_field") and re.search(ABSENCE_RX, hay, re.I):
            k = norm(f["text"])[:40]
            if k in seen:
                continue
            seen.add(k)
            out.append(_gap("stated", "medium" if f["type"] in ("risk", "deadline") else "low", f["text"][:100],
                            "The file notes this material as missing or outstanding.", [src(f)],
                            "Obtain the outstanding material or record why it is unavailable.", f.get("entity"), None, [f]))
    return sorted(out, key=lambda g: g["severity"] != "medium")[:10]


def dependencies(attention: dict | None) -> list[dict]:
    """Open requests waiting on someone else (from the digest's attention panel)."""
    out = []
    for w in (attention or {}).get("waiting", []):
        overdue = bool(w.get("due") and w["due"] < date.today().isoformat())
        ref = {"source_type": w["source_type"], "source_id": w["source_id"], "page": None, "quote": w["title"], "text": w["title"], "date": w.get("due")}
        out.append({**_gap("dependency", "high" if overdue else "medium",
                           f"Waiting on {w.get('waiting_on') or 'a third party'}" + (" (overdue)" if overdue else ""),
                           f"Open request: {w.get('detail') or w['title']}", [ref],
                           f"Follow up with {w.get('waiting_on') or 'the responsible party'}.", w.get("waiting_on"), None, [],
                           issue_type="dependency", extra_key=w["source_id"]), "due": w.get("due")})
    return out


def chronology_gaps(facts, max_days: int = 150, start: str | None = None) -> list[dict]:
    dated = sorted({f["date"] for f in facts if f["type"] == "treatment" and f.get("date") and f["date"] <= date.today().isoformat()
                    and (not start or f["date"] >= start)})
    out = []
    for a, b in zip(dated, dated[1:]):
        days = (date.fromisoformat(b) - date.fromisoformat(a)).days
        if days > max_days:
            before = next(f for f in facts if f.get("date") == a and f["type"] == "treatment")
            after = next(f for f in facts if f.get("date") == b and f["type"] == "treatment")
            out.append(_gap("chronology", "low", f"No documented treatment for {days} days",
                            f"Treatment entries jump from {a} to {b}.", [src(before), src(after)],
                            "Check whether treatment continued in this period and request those records.", None, None, [before, after],
                            issue_type="timeline_gap", extra_key=f"{a}:{b}"))
    return out


def detect(facts, docs, bundle, attention=None, include_dependencies=True) -> tuple[list[dict], list[dict]]:
    g, chain = provider_gaps(facts, docs, bundle)
    proc = pending_procedures(facts)
    from .contradictions import incident_date
    doi = incident_date(facts)
    issues = g + imaging_gap(facts, docs) + proc + stated_absences(facts) + chronology_gaps(facts, start=doi["date"] if doi else None)
    if include_dependencies:
        issues += dependencies(attention)
    for p in proc:  # pending steps go at the end of the care chain, drawn as "?"
        chain.append({"name": p["step"], "role": "pending", "first_date": None, "records": [], "bills": [], "charges": None,
                      "mentions": len(p["related_fact_ids"]), "issues": [p["id"]], "pending": True})
    return issues, chain
