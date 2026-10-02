"""VERIFIER AGENT: every claim is checked against the source it cites.

1. Code: the quote must appear in the cited source (letters/digits compared, so OCR spacing
   does not matter). If it does not, we try once to re-anchor it: fuzzy-align the quote to the
   source and, at >= 90 similarity, replace it with the source's own words. Otherwise the fact
   is `unsupported` and never shown, shared or signed.
2. LLM (Groq): "does this quote support this exact claim?" -> supported / partial / unsupported.
   Structured facts (rendered straight from a Clio field) skip this step: the claim *is* the field.
3. Document facts get their page and highlight boxes here, so the viewer can jump straight to them.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from .. import db
from ..documents import locate_snippet, norm_compact
from ..llm import LLMUnavailable, available_providers, complete_json


class Verdict(BaseModel):
    id: str
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str


class Verdicts(BaseModel):
    results: list[Verdict]


VERIFY_PROMPT = """You check claims in a legal case digest against the quote each claim cites.
For each item decide if the QUOTE supports the CLAIM exactly as written (numbers, dates, names, direction of meaning).
supported = the quote fully backs the claim; partial = related but the claim says more or differs in a detail;
unsupported = the quote does not back the claim. Give a short reason (<= 15 words).

ITEMS:
{items}

Return {{"results": [{{"id": ..., "verdict": ..., "reason": ...}}]}} with one result per item."""


def _source_text(fact: dict, page_cache: dict) -> tuple[str, list | None, int | None]:
    if fact["source_type"] == "document":
        key = fact["source_id"]
        if key not in page_cache:
            page_cache[key] = db.query("SELECT page, text, words_json FROM doc_pages WHERE doc_id=? ORDER BY page", (key,))
        pages = page_cache[key]
        return "", pages, fact["page"]
    row = db.one("SELECT text FROM sources WHERE source_type=? AND source_id=?", (fact["source_type"], fact["source_id"]))
    return (row or {}).get("text", ""), None, None


def _reanchor(quote: str, text: str) -> str | None:
    from rapidfuzz import fuzz

    if not text or not quote:
        return None
    al = fuzz.partial_ratio_alignment(quote.lower(), text.lower(), score_cutoff=90)
    if not al:
        return None
    return text[al.dest_start:al.dest_end].strip()


def code_check(fact: dict, page_cache: dict) -> dict:
    """Returns updates for the fact: quote_ok, quote (maybe re-anchored), page, bbox."""
    text, pages, hint = _source_text(fact, page_cache)
    q = fact["quote"] or ""
    if pages is None:
        if norm_compact(q) and norm_compact(q) in norm_compact(text):
            return {"quote_ok": True}
        fixed = _reanchor(q, text)
        return {"quote_ok": bool(fixed), "quote": fixed or q, "reanchored": bool(fixed)}
    # documents: hinted page first, then all pages
    order = list(pages)
    if hint:
        order.sort(key=lambda p: 0 if p["page"] == hint else 1)
    best = None
    for p in order:
        words = json.loads(p["words_json"])
        res = locate_snippet(words, q, min_score=85)
        if res["match"] == "exact" or (res["match"] == "fuzzy" and res["score"] >= 85):
            return {"quote_ok": True, "page": p["page"], "bbox": res["bboxes"], "match": res["match"]}
        if res["score"] and (not best or res["score"] > best[1]["score"]):
            best = (p["page"], res)
    return {"quote_ok": False, "page": hint or (best[0] if best else None), "bbox": []}


def run_verifier(progress=None) -> dict[str, int]:
    facts = db.query("SELECT * FROM facts WHERE verify_status IN ('pending') OR verify_status IS NULL")
    page_cache: dict = {}
    to_llm = []
    stats = {"checked": len(facts), "supported": 0, "partial": 0, "unsupported": 0, "unchecked": 0}
    for i, f in enumerate(facts):
        if progress and i % 50 == 0:
            progress(f"Verifying claims against sources ({i}/{len(facts)})")
        res = code_check(f, page_cache)
        upd = {"quote": res.get("quote", f["quote"]), "page": res.get("page", f["page"]),
               "bbox_json": json.dumps(res.get("bbox") or [])}
        if not res["quote_ok"]:
            upd.update(verify_status="unsupported", verify_reason="Quote not found in the cited source.")
        elif f["extractor"] == "structured":
            upd.update(verify_status="supported", verify_reason="Rendered directly from the Clio record.")
        elif f["extractor"] == "heuristic":
            upd.update(verify_status="supported", verify_reason="Claim is the source sentence itself (heuristic mode).")
        else:
            upd.update(verify_status="quote_ok",
                       verify_reason="Quote found in source" + (" (re-anchored)." if res.get("reanchored") else "."))
            to_llm.append({**f, **upd})
        with db.tx() as c:
            c.execute("UPDATE facts SET quote=?, page=?, bbox_json=?, verify_status=?, verify_reason=? WHERE fact_id=?",
                      (upd["quote"], upd["page"], upd["bbox_json"], upd["verify_status"], upd["verify_reason"], f["fact_id"]))

    # LLM semantic check, batched
    if to_llm and available_providers():
        batch_size = 25
        for b in range(0, len(to_llm), batch_size):
            batch = to_llm[b:b + batch_size]
            if progress:
                progress(f"Checking that each quote supports its claim ({b}/{len(to_llm)})")
            items = "\n".join(f'- id: {f["fact_id"]}\n  CLAIM: {f["text"]}' + (f' (amount {f["amount"]})' if f["amount"] else "")
                              + (f' (date {f["date"]})' if f["date"] else "") + f'\n  QUOTE: "{f["quote"]}"' for f in batch)
            try:
                verdicts = {v.id: v for v in complete_json("verifier", VERIFY_PROMPT.format(items=items), Verdicts).results}
            except LLMUnavailable:
                break
            with db.tx() as c:
                for f in batch:
                    v = verdicts.get(f["fact_id"])
                    if v:
                        c.execute("UPDATE facts SET verify_status=?, verify_reason=? WHERE fact_id=?",
                                  (v.verdict, v.reason, f["fact_id"]))
    for r in db.query("SELECT verify_status s, COUNT(*) n FROM facts GROUP BY verify_status"):
        if r["s"] in stats:
            stats[r["s"]] = r["n"]
        elif r["s"] == "quote_ok":
            stats["unchecked"] = r["n"]
    return stats


VISIBLE = ("supported", "partial", "quote_ok")
SHAREABLE = ("supported",)
