"""INGEST (code): Clio bundle -> raw_records + normalized `sources` + documents/doc_pages.

Every quotable thing becomes a row in `sources` with its full text, so the verifier and
the source viewer can check any quote against exactly what Clio returned.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import db
from .config import OCR_CACHE_DIR
from .documents import classify_document, extract_pages


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def build_sources(b: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per quotable Clio record. Text is what a human would read in Clio."""
    out: list[dict[str, Any]] = []
    m = b["matter"]

    def add(stype, sid, title, date, text, meta=None):
        out.append({"source_type": stype, "source_id": str(sid), "title": title, "date": date,
                    "text": text or "", "meta": meta or {}})

    add("matter", m["id"], m.get("display_number") or m.get("description"), m.get("open_date"),
        "\n".join(f"{k.replace('_', ' ').title()}: {v}" for k, v in [
            ("description", m.get("description")), ("status", m.get("status")), ("open_date", m.get("open_date")),
            ("statute_of_limitations", m.get("statute_of_limitations")), ("matter_stage", m.get("stage")),
            ("practice_area", m.get("practice_area")), ("responsible_attorney", m.get("responsible_attorney"))] if v),
        {"display_number": m.get("display_number")})
    for f in b["custom_fields"]:
        v = f["value"]
        shown = _money(v) if f.get("field_type") == "currency" else ("Yes" if v is True else "No" if v is False else str(v))
        add("custom_field", f["id"], f["name"], None, f"{f['name']}: {shown}", {"field_type": f.get("field_type"), "value": v})
    for c in b["contacts"]:
        lines = [c.get("name"), c.get("relationship"), c.get("company"), c.get("email"), c.get("phone"), c.get("address")]
        add("contact", c["id"], c.get("name"), None, "\n".join(x for x in lines if x), c)
    for n in b["notes"]:
        add("note", n["id"], n.get("subject"), n.get("date"), f"{n.get('subject') or ''}\n\n{n.get('detail') or ''}".strip(),
            {"updated_at": n.get("updated_at")})
    for x in b["communications"]:
        add("communication", x["id"], x.get("subject"), x.get("date"), f"{x.get('subject') or ''}\n\n{x.get('body') or ''}".strip(),
            {"type": x.get("type"), "senders": x.get("senders"), "receivers": x.get("receivers")})
    for t in b["tasks"]:
        add("task", t["id"], t.get("name"), t.get("due_at"), f"{t.get('name') or ''}\n\n{t.get('description') or ''}".strip(),
            {"status": t.get("status"), "due_at": t.get("due_at"), "assignee": t.get("assignee"),
             "statute_of_limitations": t.get("statute_of_limitations")})
    for e in b["calendar"]:
        add("calendar", e["id"], e.get("summary"), (e.get("start_at") or "")[:10],
            f"{e.get('summary') or ''}\n\n{e.get('description') or ''}".strip(),
            {"start_at": e.get("start_at"), "end_at": e.get("end_at")})
    for x in b["expenses"]:
        add("expense", x["id"], (x.get("note") or "Expense").split("\n")[0][:80], x.get("date"),
            f"Expense {_money(x['total'])} on {x.get('date')}\n\n{x.get('note') or ''}", {"total": x["total"]})
    for s in out:
        s["sha256"] = sha(s["text"])
    return out


def content_hash(b: dict[str, Any], sources: list[dict]) -> str:
    parts = sorted(f"{s['source_type']}:{s['source_id']}:{s['sha256']}" for s in sources)
    parts += sorted(f"document:{d['id']}:{d['sha256']}" for d in b["documents"])
    parts.append(f"stage:{b['matter'].get('stage')}")
    return sha("\n".join(parts))


def ingest(b: dict[str, Any], progress=None) -> dict[str, Any]:
    sources = build_sources(b)
    fetched = b["source"]["synced_at"]
    with db.tx() as c:
        c.execute("DELETE FROM sources")
        for s in sources:
            c.execute("INSERT INTO sources(source_type,source_id,title,date,text,meta_json,sha256) VALUES(?,?,?,?,?,?,?)",
                      (s["source_type"], s["source_id"], s["title"], s["date"], s["text"], json.dumps(s["meta"]), s["sha256"]))
        for kind in ["matter", "custom_fields", "contacts", "notes", "communications", "tasks", "calendar", "expenses", "documents"]:
            items = b[kind] if isinstance(b[kind], list) else [b[kind]]
            for it in items:
                c.execute("INSERT INTO raw_records(kind,clio_id,payload_json,fetched_at) VALUES(?,?,?,?) "
                          "ON CONFLICT(kind,clio_id) DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at",
                          (kind, str(it.get("id")), json.dumps(it), fetched))

    # documents: per-page text + boxes (OCR cached by sha)
    if os.getenv("CLEARCASE_SKIP_UNCACHED_OCR") == "1":  # dev only: don't block on a long OCR run
        b["documents"] = [d for d in b["documents"] if (OCR_CACHE_DIR / f"{d['sha256']}.json").exists()]
    for i, d in enumerate(b["documents"]):
        if progress:
            progress(f"Reading document {i + 1}/{len(b['documents'])}: {d['name']}")
        path = Path(d["local_path"])
        pages = extract_pages(path, d["sha256"])
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO documents(id,clio_id,name,folder,doc_type,sha256,page_count,local_path,received_at,scanned_pages) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (d["id"], d["clio_id"], d["name"], d.get("folder"), classify_document(d["name"], d.get("folder")),
                       d["sha256"], len(pages), str(path), d.get("received_at"), sum(p["method"] == "ocr" for p in pages)))
            c.execute("DELETE FROM doc_pages WHERE doc_id=?", (d["id"],))
            c.executemany("INSERT INTO doc_pages(doc_id,page,text,words_json,method,width,height) VALUES(?,?,?,?,?,?,?)",
                          [(d["id"], p["page"], p["text"], json.dumps(p["words"]), p["method"], p["width"], p["height"]) for p in pages])
    h = content_hash(b, sources)
    db.set_setting("last_sync", {**b["source"], "content_hash": h, "record_count": len(sources) + len(b["documents"])})
    db.set_setting("bundle", {k: v for k, v in b.items() if k != "raw"})
    return {"content_hash": h, "sources": len(sources), "documents": len(b["documents"])}
