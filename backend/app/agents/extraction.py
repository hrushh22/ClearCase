"""EXTRACTION AGENT: every source -> facts[] with an exact quote and a source pointer.

Three extractors, all producing the same Fact shape:
  structured - plain code over Clio's structured records (custom fields, tasks, calendar,
               expenses, matter dates). The quote is the exact rendered field text.
  llm        - Mistral over notes, communications and document pages (batched, cached by source hash).
  heuristic  - fallback when no LLM key is configured: sentence-level facts picked by money/date/
               keyword cues. Labeled "heuristic" everywhere so nobody mistakes it for the real thing.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .. import db
from ..llm import LLMUnavailable, available_providers, complete_json

WORKERS = 5

FactType = Literal["injury", "treatment", "provider", "bill", "lien", "payment", "coverage", "demand", "offer",
                   "deadline", "filing", "contact", "client_event", "expense", "valuation", "risk", "other"]


class Fact(BaseModel):
    fact_id: str = ""
    type: FactType
    text: str = Field(description="short plain-language fact")
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD or null")
    amount: Optional[float] = None
    entity: Optional[str] = Field(default=None, description="provider/party name or null")
    source_type: str = ""
    source_id: str = ""
    page: Optional[int] = None
    quote: str = Field(description="exact short snippet copied from the source, <= 25 words")
    confidence: float = 0.8


class LLMFact(BaseModel):
    source_ref: str = Field(description="the [ref] label of the source this fact came from")
    type: FactType
    text: str
    date: Optional[str] = None
    amount: Optional[float] = None
    entity: Optional[str] = None
    page: Optional[int] = None
    quote: str
    confidence: float = 0.8


class LLMFacts(BaseModel):
    facts: list[LLMFact]


def fact_id(*parts: Any) -> str:
    return "f_" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _date(s: Any) -> Optional[str]:
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s))
    return m.group(1) if m else None


def _first_amount(text: str) -> Optional[float]:
    m = re.search(r"\$\s?([0-9][0-9,]*(?:\.\d{2})?)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


# ------------------------------------------------------------------ structured (code)

CF_TYPES = [  # (regex on field name, fact type)
    (r"date of (incident|loss|accident)", "client_event"), (r"case value|valuation", "valuation"),
    (r"medical specials|specials", "bill"), (r"policy|insurance|carrier|coverage|claim number", "coverage"),
    (r"lien|health insurance", "lien"), (r"wage|income", "other"), (r"liability", "risk"),
    (r"prior.*injur", "risk"), (r"treatment", "treatment"), (r"location", "client_event"),
    (r"summary", "client_event"), (r"hipaa|authori", "other"),
]


def structured_facts(sources: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    for s in sources:
        st, sid, text, meta = s["source_type"], s["source_id"], s["text"], s["meta"]
        if st == "custom_field":
            name = s["title"] or ""
            ftype = next((t for rx, t in CF_TYPES if re.search(rx, name, re.I)), "other")
            value = meta.get("value")
            first_line = text.split("\n")[0]
            amount = float(value) if meta.get("field_type") == "currency" and value is not None else None
            facts.append(Fact(type=ftype, text=first_line, date=_date(value) if meta.get("field_type") == "date" else None,
                              amount=amount, source_type=st, source_id=sid, quote=" ".join(first_line.split()[:25]),
                              confidence=1.0))
        elif st == "task":
            name = s["title"] or ""
            entity = None
            m = re.match(r"By medical provider:\s*(.+?)\s+-\s+", name)
            if m:
                entity = m.group(1)
            facts.append(Fact(type="deadline", text=f"Task ({meta.get('status')}): {name}", date=_date(meta.get("due_at")),
                              entity=entity, source_type=st, source_id=sid, quote=" ".join(name.split()[:25]), confidence=1.0))
        elif st == "calendar":
            name = s["title"] or ""
            ftype = "treatment" if re.search(r"treatment|surgery|arthroscopy|consult|IME|therapy|chiropractic", name, re.I) else "client_event"
            facts.append(Fact(type=ftype, text=name, date=_date(meta.get("start_at")), source_type=st, source_id=sid,
                              quote=" ".join(name.split()[:25]), confidence=1.0))
        elif st == "expense":
            first = text.split("\n")[0]
            facts.append(Fact(type="expense", text=first + " - " + (text.split("\n\n", 1)[-1].split("\n")[0])[:120],
                              date=s["date"], amount=meta.get("total"), source_type=st, source_id=sid,
                              quote=first, confidence=1.0))
        elif st == "matter":
            for line in text.split("\n"):
                if re.match(r"(Open Date|Statute Of Limitations):", line):
                    facts.append(Fact(type="deadline" if "Statute" in line else "filing", text=line, date=_date(line.split(": ", 1)[1]),
                                      source_type=st, source_id=sid, quote=line, confidence=1.0))
    for f in facts:
        f.fact_id = fact_id(f.source_type, f.source_id, f.type, f.quote)
    return facts


# ------------------------------------------------------------------------ LLM

EXTRACT_PROMPT = """You are a paralegal reading a personal-injury case file (client: {client}).
Extract the facts an attorney or a treating medical provider would need. Fact types:
injury (diagnosis / body part), treatment (visit, surgery, therapy, imaging, who treated), provider (a treating provider and role),
bill (an amount charged by a named provider), lien (an asserted lien and amount), payment (amount paid), coverage (insurance/policy/self-insured facts),
demand (settlement demand), offer (offer from the other side), deadline (due date / court date), filing (court filing, pleading, discovery event),
contact (communication with the client), client_event (what happened to the client, work status, accident facts), valuation (what the case is worth),
risk (contradictions, weaknesses, liability problems), other.

Rules:
- "quote" MUST be copied character-for-character from the source text (<= 25 words). No paraphrase in quote.
- "text" is one short plain-English sentence.
- date as YYYY-MM-DD only if the source states it; amount as a number only if stated.
- entity = provider or party name if the fact is about one.
- For document pages, set "page" to the page number shown in the [ref] header.
- Skip boilerplate, headers, fax lines, signatures, and repeated form text. At most {max_facts} facts total.

SOURCES:
{sources}
"""


def _chunks_for_records(sources: list[dict], limit_chars: int = 9000) -> list[list[dict]]:
    batches, cur, size = [], [], 0
    for s in sources:
        n = len(s["text"])
        if cur and size + n > limit_chars:
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += n
    if cur:
        batches.append(cur)
    return batches


def _doc_page_chunks(doc: dict, pages: list[dict], limit_chars: int = 10000) -> list[list[dict]]:
    batches, cur, size = [], [], 0
    for p in pages:
        text = p["text"][:6000]
        if len(text.strip()) < 40:
            continue
        if cur and size + len(text) > limit_chars:
            batches.append(cur)
            cur, size = [], 0
        cur.append({**p, "text": text})
        size += len(text)
    if cur:
        batches.append(cur)
    return batches


def _anchor_llm_facts(raw: LLMFacts, refs: dict[str, dict]) -> list[Fact]:
    out = []
    for lf in raw.facts:
        src = refs.get(lf.source_ref.strip("[] "))
        if not src:
            continue
        page = src.get("page") or lf.page
        f = Fact(type=lf.type, text=lf.text, date=_date(lf.date), amount=lf.amount, entity=lf.entity,
                 source_type=src["source_type"], source_id=src["source_id"], page=page,
                 quote=" ".join(lf.quote.split()[:30]), confidence=max(0.0, min(1.0, lf.confidence)))
        f.fact_id = fact_id(f.source_type, f.source_id, f.page, f.type, f.quote)
        out.append(f)
    return out


def llm_extract_records(batch: list[dict], client: str) -> list[Fact]:
    refs, blocks = {}, []
    for i, s in enumerate(batch):
        ref = f"S{i + 1}"
        refs[ref] = s
        blocks.append(f"[{ref}] {s['source_type']} dated {s['date']}: {s['title']}\n{s['text']}")
    raw = complete_json("extraction", EXTRACT_PROMPT.format(client=client, sources="\n\n".join(blocks),
                                                            max_facts=6 * len(batch)), LLMFacts)
    return _anchor_llm_facts(raw, refs)


def llm_extract_pages(doc: dict, chunk: list[dict], client: str) -> list[Fact]:
    refs, blocks = {}, []
    for p in chunk:
        ref = f"P{p['page']}"
        refs[ref] = {"source_type": "document", "source_id": doc["id"], "page": p["page"]}
        blocks.append(f"[{ref}] document '{doc['name']}' ({doc['doc_type']}), page {p['page']}:\n{p['text']}")
    raw = complete_json("extraction", EXTRACT_PROMPT.format(client=client, sources="\n\n".join(blocks),
                                                            max_facts=4 * len(chunk) + 4), LLMFacts)
    return _anchor_llm_facts(raw, refs)


# ------------------------------------------------------------------ heuristic fallback

KEYWORDS = [
    (r"\blien\b", "lien"), (r"self-insured|policy|coverage|UM/UIM|no-fault|limits?\b", "coverage"),
    (r"\bdemand\b", "demand"), (r"\boffer\b", "offer"), (r"surgery|arthroscopy|therapy|chiropractic|treat|MRI|imaging|EMG", "treatment"),
    (r"injur|tear|fracture|sprain|radiculopathy|concussion|impingement|diagnos", "injury"),
    (r"complaint|summons|discovery|deposition|conference|subpoena|bill of particulars|IME", "filing"),
    (r"contradict|discrepan|denies|three different|not investigated|problem|risk", "risk"),
    (r"worth|valuation|value", "valuation"), (r"out of work|wage|commission", "client_event"),
]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -") for p in parts if len(p.strip()) > 25]


def heuristic_facts(sources: list[dict]) -> list[Fact]:
    facts = []
    for s in sources:
        if s["source_type"] not in ("note", "communication"):
            continue
        for sent in _sentences(s["text"]):
            ftype = next((t for rx, t in KEYWORDS if re.search(rx, sent, re.I)), None)
            amount = _first_amount(sent)
            if not ftype and amount is None:
                continue
            if amount is not None and ftype in (None, "treatment", "injury", "other"):
                listed = re.search(r":\s*\$[0-9,.]+\s*$", sent)  # "- Provider, detail: $1,234.00"
                ftype = "bill" if listed or re.search(r"visits?|sessions?|studies|\bER\b|surgical|imaging", sent, re.I) else (ftype or "other")
            quote = " ".join(sent.split()[:25])
            entity = None
            if ftype == "bill":
                m = re.match(r"^([A-Z][\w.&'/ -]+?),", sent)
                entity = m.group(1).strip() if m else None
            elif ftype == "lien" and amount:
                m = re.search(r"((?:[A-Z][\w.&'-]*\s){1,5})lien\b(.*)", sent)
                entity = m.group(1).strip() if m else None
                amount = _first_amount(m.group(2)) if m else None  # the figure that follows "lien", not any figure
            f = Fact(type=ftype, text=sent[:220], date=s["date"], amount=amount, entity=entity, source_type=s["source_type"],
                     source_id=s["source_id"], quote=quote, confidence=0.5)
            f.fact_id = fact_id(f.source_type, f.source_id, f.type, f.quote)
            facts.append(f)
    return facts


def heuristic_doc_facts(doc: dict, pages: list[dict]) -> list[Fact]:
    """Diagnosis / impression lines from medical and expert documents."""
    facts, seen = [], set()
    if doc["doc_type"] not in ("medical_record", "bill", "expert_report"):
        return facts
    for p in pages:
        for line in p["text"].split("\n"):
            if re.search(r"impression|diagnos|ICD.?10|assessment", line, re.I) and 20 < len(line) < 200:
                key = re.sub(r"\W", "", line.lower())[:60]
                if key in seen:
                    continue
                seen.add(key)
                f = Fact(type="injury", text=line.strip()[:200], source_type="document", source_id=doc["id"], page=p["page"],
                         quote=" ".join(line.split()[:25]), confidence=0.4)
                f.fact_id = fact_id("document", doc["id"], p["page"], f.quote)
                facts.append(f)
                if len(facts) >= 40:
                    return facts
    return facts


# ------------------------------------------------------------------------ driver

def _done(stype: str, sid: str, part: str, sha: str) -> bool:
    row = db.one("SELECT source_sha, extractor FROM extraction_runs WHERE source_type=? AND source_id=? AND part=?", (stype, sid, part))
    mode = "llm" if available_providers() else "heuristic"
    return bool(row and row["source_sha"] == sha and row["extractor"] == mode)


def _save(facts: list[Fact], extractor: str, runs: list[tuple[str, str, str, str]]) -> None:
    with db.tx() as c:
        for stype, sid, part, sha in runs:
            c.execute("DELETE FROM facts WHERE source_type=? AND source_id=? AND (?='all' OR page=CAST(? AS INTEGER))",
                      (stype, sid, part, part))
            c.execute("INSERT OR REPLACE INTO extraction_runs(source_type,source_id,part,source_sha,extractor,created_at) VALUES(?,?,?,?,?,?)",
                      (stype, sid, part, sha, extractor, db.now_iso()))
        for f in facts:
            c.execute("INSERT OR REPLACE INTO facts(fact_id,type,text,date,amount,entity,source_type,source_id,page,quote,confidence,"
                      "extractor,created_at,verify_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f.fact_id, f.type, f.text, f.date, f.amount, f.entity, f.source_type, f.source_id, f.page, f.quote,
                       f.confidence, extractor, db.now_iso(), "pending"))


def run_extraction(progress=None) -> dict[str, int]:
    """Extract facts for every source whose content changed since the last run."""
    sources = [{**s, "meta": json.loads(s["meta_json"] or "{}")} for s in db.query("SELECT * FROM sources")]
    bundle = db.get_setting("bundle", {})
    client = (bundle.get("matter") or {}).get("client_name") or "the client"
    use_llm = bool(available_providers())
    mode = "llm" if use_llm else "heuristic"
    stats = {"structured": 0, "records": 0, "doc_chunks": 0, "skipped": 0}

    # structured: always code, always fully refreshed (cheap)
    structured_types = ("custom_field", "task", "calendar", "expense", "matter")
    st_sources = [s for s in sources if s["source_type"] in structured_types]
    with db.tx() as c:
        c.execute(f"DELETE FROM facts WHERE extractor='structured'")
    _save(structured_facts(st_sources), "structured", [])
    stats["structured"] = len(st_sources)

    # notes + communications
    todo = [s for s in sources if s["source_type"] in ("note", "communication")
            and not _done(s["source_type"], s["source_id"], "all", s["sha256"])]
    stats["skipped"] += len([s for s in sources if s["source_type"] in ("note", "communication")]) - len(todo)
    if use_llm:
        batches = _chunks_for_records(todo)
        done = [0]

        def one(batch):
            try:
                facts, mode_used = llm_extract_records(batch, client), "llm"
            except LLMUnavailable:
                facts, mode_used = heuristic_facts(batch), "heuristic"
            _save(facts, mode_used, [(s["source_type"], s["source_id"], "all", s["sha256"]) for s in batch])
            done[0] += 1
            if progress:
                progress(f"Extracting facts from notes and emails ({done[0]}/{len(batches)})")

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(one, batches))
        stats["records"] += len(todo)
    elif todo:
        _save(heuristic_facts(todo), "heuristic", [(s["source_type"], s["source_id"], "all", s["sha256"]) for s in todo])
        stats["records"] += len(todo)

    # documents, page chunks
    for doc in db.query("SELECT * FROM documents ORDER BY received_at"):
        if _done("document", doc["id"], "all", doc["sha256"]):
            stats["skipped"] += 1
            continue
        pages = db.query("SELECT page, text FROM doc_pages WHERE doc_id=? ORDER BY page", (doc["id"],))
        facts: list[Fact] = []
        used = mode
        if use_llm:
            chunks = _doc_page_chunks(doc, pages)
            done = [0]

            def one(chunk):
                try:
                    out = (llm_extract_pages(doc, chunk, client), "llm")
                except LLMUnavailable:
                    out = (heuristic_doc_facts(doc, chunk), "heuristic")
                done[0] += 1
                if progress:
                    progress(f"Reading {doc['name']} ({done[0]}/{len(chunks)} parts)")
                return out

            with ThreadPoolExecutor(max_workers=WORKERS) as pool:  # rate limiters in llm.py pace the calls
                for chunk_facts, how in pool.map(one, chunks):
                    facts += chunk_facts
                    used = "heuristic" if how == "heuristic" else used
            stats["doc_chunks"] += len(chunks)
        else:
            facts = heuristic_doc_facts(doc, pages)
        with db.tx() as c:
            c.execute("DELETE FROM facts WHERE source_type='document' AND source_id=?", (doc["id"],))
        _save(facts, used, [("document", doc["id"], "all", doc["sha256"])])
    return stats
