"""PRIORITY AGENT: out of every note, email and task, the ten that matter.

Groq scores each entry for case impact (batched to stay under the free-tier token budget).
Ties break deterministically: score desc, then date desc, then id. Without an LLM, a labeled
keyword+recency score is used instead.
"""
from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from ..llm import LLMUnavailable, available_providers, complete_json


class Score(BaseModel):
    ref: str
    score: int
    why_it_matters: str


class Scores(BaseModel):
    items: list[Score]


PROMPT = """You are a senior personal-injury attorney triaging a case file for a colleague taking it over.
Score each entry 0-100 for how much it matters to the case outcome right now (coverage, value, liability problems,
open blockers, deadlines, client credibility, liens). Routine admin (records requests, scheduling, invoices) scores low.
why_it_matters: one line, <= 18 words, plain English, specific.
Today is {today}.
ENTRIES:
{entries}
Return {{"items": [{{"ref", "score", "why_it_matters"}}]}} for every entry."""

HEURISTIC = [(r"\bcoverage\b|\blimits?\b|self-insured|\bpolicy\b", 16), (r"\bliens?\b|\bmedicaid\b", 12),
             (r"contradict|discrepan|three different|\bdenie[sd]\b|\bprior\b", 16), (r"\bsurgery\b|\bsurgical\b", 10),
             (r"\bvalu(e|ation)\b|\bworth\b|\bdemand\b|\boffer\b", 12), (r"\bstuck\b|\bblocked\b|not done|no date", 10),
             (r"conference|deadline|limitations|\bIME\b|\bexpert\b", 6), (r"records request|\binvoice\b|chaser|enclosed", -15)]


def _heuristic(s: dict, today: str) -> tuple[int, str]:
    text = (s["title"] or "") + " " + s["text"][:1500]
    score = 20 + sum(w for rx, w in HEURISTIC if re.search(rx, text, re.I)) + min(len(s["text"]) // 200, 8)
    if s.get("date") and s["date"] >= str(int(today[:4]) - 1) + today[4:]:
        score += 10
    hits = [re.sub(r"\\b|\(|\)|\?", "", rx.split("|")[0]) for rx, w in HEURISTIC if w > 0 and re.search(rx, text, re.I)]
    return max(0, min(100, score)), ("Mentions " + ", ".join(hits[:3]) + " (keyword score)") if hits else "Recent activity (keyword score)"


def top10(sources: list[dict]) -> dict:
    today = date.today().isoformat()
    cands = [s for s in sources if s["source_type"] in ("note", "communication", "task")]
    scored: dict[str, tuple[int, str, str]] = {}
    method = "heuristic"
    if available_providers():
        try:
            for i in range(0, len(cands), 40):
                batch = cands[i:i + 40]
                entries = "\n".join(f'[{j}] {s["source_type"]} {s.get("date")}: {s["title"]} :: {" ".join(s["text"].split())[:280]}'
                                    for j, s in enumerate(batch))
                r = complete_json("priority", PROMPT.format(today=today, entries=entries), Scores)
                for it in r.items:
                    idx = int(re.sub(r"\D", "", it.ref) or -1)
                    if 0 <= idx < len(batch):
                        s = batch[idx]
                        scored[f'{s["source_type"]}:{s["source_id"]}'] = (it.score, it.why_it_matters, "llm")
            method = "llm"
        except LLMUnavailable:
            scored = {}
    for s in cands:
        k = f'{s["source_type"]}:{s["source_id"]}'
        if k not in scored:
            sc, why = _heuristic(s, today)
            scored[k] = (sc, why, "heuristic")
    ranked = sorted(cands, key=lambda s: (-scored[f'{s["source_type"]}:{s["source_id"]}'][0],
                                          "".join(chr(255 - ord(c)) for c in (s.get("date") or "")), s["source_id"]))
    items = []
    for s in ranked[:10]:
        sc, why, m = scored[f'{s["source_type"]}:{s["source_id"]}']
        items.append({"source_type": s["source_type"], "source_id": s["source_id"], "title": s["title"], "date": s.get("date"),
                      "score": sc, "why_it_matters": why, "method": m,
                      "quote": " ".join(s["text"].split()[:25])})
    return {"items": items, "method": method, "considered": len(cands)}
