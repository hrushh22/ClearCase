"""STRESS TEST MY CASE: adversarial review of evidence quality and completeness (not legal advice, not a prediction).

A. Supporting Case Analyst  - strongest source-backed support per proposition
B. Adversarial Reviewer     - challenges using ONLY evidence in the file (contradictions, gaps, timing, weak corroboration)
C. Evidence Judge           - code check (every cited fact id must be a real verified fact) + LLM check of each item

Without an LLM, a deterministic version is produced from the support states and issues (labeled).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..llm import LLMUnavailable, available_providers, complete_json
from .common import src


class SupportItem(BaseModel):
    proposition_id: str
    summary: str
    fact_ids: list[str]


class SupportOut(BaseModel):
    items: list[SupportItem]


class Challenge(BaseModel):
    proposition_id: str
    challenge: str
    kind: Literal["contradiction", "missing_proof", "timing", "weak_corroboration", "gap", "amount", "none"]
    fact_ids: list[str]
    issue_ids: list[str] = []


class ChallengeOut(BaseModel):
    items: list[Challenge]


class Verdict(BaseModel):
    ref: str
    verdict: Literal["accept", "needs_review", "reject"]
    reason: str


class Verdicts(BaseModel):
    items: list[Verdict]


A_PROMPT = """You are the Supporting Case Analyst on a personal-injury file. For each proposition, summarize in <= 25 words the
strongest support, citing ONLY fact ids listed under it. Do not add facts. Skip a proposition with no real support.
PROPOSITIONS:
{props}"""

B_PROMPT = """You are an Adversarial Reviewer checking evidence quality on a personal-injury file. For each proposition, challenge it
using ONLY the facts and open issues listed (contradictions, missing proof, timing, weak corroboration, inconsistent amounts).
Never invent evidence, witnesses or arguments not in the list. If nothing in the list challenges it, return kind "none" with
challenge "No contradictory source was found." Each challenge <= 30 words, cite fact ids and/or issue ids from the list.
PROPOSITIONS:
{props}
OPEN ISSUES:
{issues}"""

C_PROMPT = """You are the Evidence Judge. For each item, check that the cited facts actually support what the item says.
accept = fully grounded; needs_review = partly grounded or overstated; reject = not grounded in the cited facts.
Reason <= 15 words.
ITEMS:
{items}"""


def _props_block(props, by_id, n=6):
    lines = []
    for p in props:
        lines.append(f"[{p['id']}] {p['title']} (state: {p['state_label']})")
        for fid in p["fact_ids"][:n]:
            f = by_id.get(fid)
            if f:
                lines.append(f"   - [{fid}] {f['text'][:150]}")
    return "\n".join(lines)


def run(props: list[dict], issues: list[dict], facts: list[dict]) -> dict:
    by_id = {f["fact_id"]: f for f in facts}
    by_issue = {i["id"]: i for i in issues}
    prop_ids = {p["id"]: p for p in props}
    gaps = [i for i in issues if i["issue_type"] in ("missing_evidence", "dependency", "timeline_gap") and i.get("verify_status") != "hidden"]
    out = {"method": "deterministic", "strong": [], "vulnerabilities": [], "gaps": [], "follow_ups": [], "rejected": 0}

    def valid_ids(ids):  # judge, code half: only real, verified facts count as evidence
        return [i for i in ids if i in by_id and by_id[i]["verify_status"] in ("supported", "partial")]

    used_llm = False
    if available_providers():
        try:
            a = complete_json("stress", A_PROMPT.format(props=_props_block(props, by_id)), SupportOut)
            issues_block = "\n".join(f"[{i['id']}] {i['issue_type']}: {i['title']} (facts: {', '.join(i.get('related_fact_ids', [])[:3])})"
                                     for i in issues if i.get("verify_status") != "hidden")[:6000]
            b = complete_json("stress", B_PROMPT.format(props=_props_block(props, by_id, 4), issues=issues_block or "(none)"), ChallengeOut)
            strong = [s for s in a.items if s.proposition_id in prop_ids and valid_ids(s.fact_ids)]
            chal = [c for c in b.items if c.proposition_id in prop_ids and c.kind != "none" and
                    (valid_ids(c.fact_ids) or [x for x in c.issue_ids if x in by_issue])]
            none = [c for c in b.items if c.kind == "none" and c.proposition_id in prop_ids]
            out["rejected"] = (len(a.items) - len(strong)) + (len(b.items) - len(chal) - len(none))
            items = [(f"S{k}", s.summary, valid_ids(s.fact_ids)) for k, s in enumerate(strong)] + \
                    [(f"V{k}", c.challenge, valid_ids(c.fact_ids) + [f"issue:{x}" for x in c.issue_ids if x in by_issue]) for k, c in enumerate(chal)]
            verdicts = {}
            if items:
                listing = "\n".join(f"- ref {r}: {t}\n  cited: " + "; ".join(
                    (by_id[i]["text"][:120] if i in by_id else by_issue[i[6:]]["title"]) for i in ids[:4]) for r, t, ids in items)
                verdicts = {v.ref: v for v in complete_json("stress", C_PROMPT.format(items=listing), Verdicts).items}
            for k, s in enumerate(strong):
                v = verdicts.get(f"S{k}")
                if v and v.verdict == "reject":
                    out["rejected"] += 1
                    continue
                out["strong"].append({"proposition_id": s.proposition_id, "proposition": prop_ids[s.proposition_id]["title"], "text": s.summary,
                                      "status": "verified" if not v or v.verdict == "accept" else "needs_review", "judge": v.reason if v else None,
                                      "evidence": [src(by_id[i]) for i in valid_ids(s.fact_ids)][:6]})
            for k, c in enumerate(chal):
                v = verdicts.get(f"V{k}")
                if v and v.verdict == "reject":
                    out["rejected"] += 1
                    continue
                ev = [src(by_id[i]) for i in valid_ids(c.fact_ids)]
                for x in c.issue_ids:
                    if x in by_issue:
                        ev += by_issue[x]["evidence_for"][:2]
                out["vulnerabilities"].append({"proposition_id": c.proposition_id, "proposition": prop_ids[c.proposition_id]["title"],
                                               "kind": c.kind, "text": c.challenge, "issue_ids": [x for x in c.issue_ids if x in by_issue],
                                               "status": "verified" if not v or v.verdict == "accept" else "needs_review",
                                               "judge": v.reason if v else None, "evidence": ev[:6]})
            for c in none:
                out["strong"].append({"proposition_id": c.proposition_id, "proposition": prop_ids[c.proposition_id]["title"],
                                      "text": "No contradictory source was found.", "status": "verified", "judge": None,
                                      "evidence": prop_ids[c.proposition_id]["evidence"][:3], "no_challenge": True})
            out["method"] = "llm"
            used_llm = True
        except LLMUnavailable:
            used_llm = False
    if not used_llm:
        for p in props:
            if p["state"] in ("well_corroborated", "supported"):
                out["strong"].append({"proposition_id": p["id"], "proposition": p["title"], "status": "verified", "judge": None,
                                      "text": f"{p['state_label']}: {p['components']['verified_sources']} verified sources across "
                                              f"{p['components']['independent_source_types']} source types.", "evidence": p["evidence"][:4]})
            for iid in p["contradictions"]:
                i = by_issue.get(iid)
                if i:
                    out["vulnerabilities"].append({"proposition_id": p["id"], "proposition": p["title"], "kind": "contradiction",
                                                   "text": f"{i['title']}: {i['explanation']}", "issue_ids": [iid], "status": i.get("verify_status"),
                                                   "judge": None, "evidence": i["evidence_for"][:4]})
    for g in gaps[:12]:
        out["gaps"].append({"issue_id": g["id"], "title": g["title"], "text": g["explanation"], "evidence": g["evidence_for"][:3],
                            "status": g.get("verify_status")})
    seen = set()
    for g in sorted(gaps, key=lambda g: {"high": 0, "medium": 1, "low": 2}[g["severity"]]):
        if g["suggested_action"] not in seen:
            seen.add(g["suggested_action"])
            out["follow_ups"].append({"issue_id": g["id"], "text": g["suggested_action"], "evidence": g["evidence_for"][:2]})
    out["follow_ups"] = out["follow_ups"][:10]
    out["disclaimer"] = ("Reviews consistency and completeness of the evidence in the file. It does not determine legal truth, "
                         "predict outcomes, or replace attorney judgment.")
    return out
