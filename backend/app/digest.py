"""Pipeline orchestrator + digest cache.

trigger (first load / Sync / changed Clio hash)
  INGEST -> DOCUMENTS -> EXTRACTION -> VERIFIER -> KPI, STAGE, TIMELINE, PRIORITY, INJURIES,
  ATTENTION, CONTACT (fan-out) -> CACHE under content hash -> change events

Opening the dashboard only reads the cached digest; it never runs an LLM.
"""
from __future__ import annotations

import json
import threading
import traceback
from typing import Any

from . import db
from .agents import code_agents, kpi, priority, stage, timeline
from .agents.extraction import run_extraction
from .agents.verifier import VISIBLE, run_verifier
from .config import firm_name
from .ingest import ingest
from .llm import available_providers, usage_report
from .source import fetch_bundle
from .waterfall import DEFAULT_FEE_PCT

_status: dict[str, Any] = {"running": False, "step": "idle", "error": None, "started_at": None, "finished_at": None}
_run_lock = threading.Lock()


def status() -> dict:
    return dict(_status)


def _progress(msg: str) -> None:
    _status["step"] = msg


def _load_sources() -> list[dict]:
    return [{**s, "meta": json.loads(s["meta_json"] or "{}")} for s in db.query("SELECT * FROM sources")]


def _visible_facts() -> list[dict]:
    rows = db.query(f"SELECT * FROM facts WHERE verify_status IN ({','.join('?' * len(VISIBLE))})", VISIBLE)
    for r in rows:
        r["bbox"] = json.loads(r.pop("bbox_json") or "[]")
    return rows


def _cleanup_orphans() -> None:
    with db.tx() as c:
        c.execute("DELETE FROM facts WHERE source_type!='document' AND NOT EXISTS "
                  "(SELECT 1 FROM sources s WHERE s.source_type=facts.source_type AND s.source_id=facts.source_id)")
        c.execute("DELETE FROM facts WHERE source_type='document' AND source_id NOT IN (SELECT id FROM documents)")


def build_digest(content_hash: str) -> dict:
    bundle = db.get_setting("bundle", {})
    sources = _load_sources()
    facts = _visible_facts()
    m = bundle["matter"]
    docs = db.query("SELECT id,name,folder,doc_type,page_count,scanned_pages,local_path,received_at FROM documents")

    _progress("Computing KPIs")
    kpis = {"case_value": kpi.case_value(facts), "coverage": kpi.coverage(facts), "specials": kpi.medical_specials(facts),
            "firm_spend": kpi.firm_spend(facts)}
    _progress("Classifying stage")
    st = stage.classify(facts, m.get("stage"), m.get("status"))
    _progress("Building timeline")
    tl = timeline.build_timeline(facts)
    _progress("Ranking the ten entries that matter")
    top = priority.top10(sources)
    _progress("Summarizing injuries and treatment")
    inj = timeline.build_injuries(facts)
    att = code_agents.attention(sources)
    contact = code_agents.client_contact(sources, m.get("client_id"), m.get("client_name"))
    client = next((c for c in bundle["contacts"] if c.get("is_client")), {})
    _progress("Looking for the client's photo")
    photo = code_agents.client_photo(docs)

    cf = {f["name"]: f["value"] for f in bundle.get("custom_fields", [])}
    incident = next((f for f in facts if f["source_type"] == "custom_field" and f["type"] == "client_event" and f.get("date")), None)
    snapshot = {
        "matter_id": m["id"], "display_number": m.get("display_number"), "title": m.get("description"), "status": m.get("status"),
        "clio_stage": m.get("stage"), "practice_area": m.get("practice_area"), "open_date": m.get("open_date"),
        "statute_of_limitations": m.get("statute_of_limitations"), "responsible_attorney": m.get("responsible_attorney"),
        "client": {"name": client.get("name") or m.get("client_name"), "dob": client.get("date_of_birth"), "email": client.get("email"),
                   "phone": client.get("phone"), "address": client.get("address"), "company": client.get("company"),
                   "photo": photo, "source": {"source_type": "contact", "source_id": client.get("id")}},
        "incident": {"date": incident["date"], "source": {k: incident[k] for k in ("fact_id", "source_type", "source_id", "quote")}} if incident else None,
        "custom_fields": [{"name": f["name"], "value": f["value"], "field_type": f.get("field_type"), "source_id": f["id"]}
                          for f in bundle.get("custom_fields", [])],
        "contacts": bundle["contacts"], "firm_name": firm_name(),
    }
    expenses = [f for f in facts if f["type"] == "expense"]
    wf_defaults = {
        "fee_pct": DEFAULT_FEE_PCT, "suggested_gross": kpis["coverage"].get("value") or kpis["case_value"].get("value") or 100000,
        "max_gross": max(kpis["case_value"].get("value") or 0, kpis["coverage"].get("value") or 0, 100000) * 1.25,
        "expenses": [{"amount": f["amount"], "label": f["text"], "source": {k: f[k] for k in ("fact_id", "source_type", "source_id", "quote")}}
                     for f in expenses],
        "liens": [{"name": p["name"], "amount": p["amount"], "kind": p["kind"], "sources": p["sources"]} for p in kpis["specials"]["providers"]],
        "assumptions": ["Attorney fee % is not in the case data (default 33.3%).",
                        "Lien reductions are negotiation assumptions (default 0%).",
                        "Payment order is an assumption (default: asserted liens first, then largest bills).",
                        "Provider bills may overlap with amounts already paid by no-fault or Medicaid; untick a line to exclude it."],
    }
    sync = db.get_setting("last_sync", {})
    digest = {
        "content_hash": content_hash, "created_at": db.now_iso(), "record_count": sync.get("record_count"),
        "source": {k: sync.get(k) for k in ("kind", "synced_at", "requests", "matter_id")},
        "snapshot": snapshot, "kpis": kpis, "stage": st, "timeline": tl, "top10": top, "attention": att,
        "injuries": inj, "contact": contact, "waterfall": wf_defaults,
        "facts": [{k: f[k] for k in ("fact_id", "type", "text", "date", "amount", "entity", "source_type", "source_id", "page", "quote",
                                     "verify_status", "verify_reason", "extractor", "confidence")} for f in facts],
        "documents": [{k: d[k] for k in ("id", "name", "folder", "doc_type", "page_count", "scanned_pages", "received_at")} for d in docs],
        "fact_stats": {r["s"] or "pending": r["n"] for r in db.query("SELECT verify_status s, COUNT(*) n FROM facts GROUP BY verify_status")},
        "extractors": {r["e"]: r["n"] for r in db.query("SELECT extractor e, COUNT(*) n FROM facts GROUP BY extractor")},
        "llm": {"providers": available_providers(), "usage": usage_report()},
        "ai_coverage": {"sampled_docs": [r["source_id"] for r in db.query(
            "SELECT source_id FROM extraction_runs WHERE source_type='document' AND extractor LIKE '%_sampled'")]},
    }
    digest["fact_ids"] = [f["fact_id"] for f in facts]
    return digest


def save_digest(d: dict) -> None:
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO digests(content_hash,created_at,record_count,snapshot_json,kpis_json,stage_json,timeline_json,"
                  "top10_json,attention_json,injuries_json,contact_json,waterfall_json,facts_json,model_log_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (d["content_hash"], d["created_at"], d["record_count"], json.dumps(d["snapshot"]), json.dumps(d["kpis"]),
                   json.dumps(d["stage"]), json.dumps(d["timeline"]), json.dumps(d["top10"]), json.dumps(d["attention"]),
                   json.dumps(d["injuries"]), json.dumps(d["contact"]), json.dumps(d["waterfall"]), json.dumps(d["facts"]),
                   json.dumps({k: d[k] for k in ("source", "documents", "fact_stats", "extractors", "llm", "fact_ids", "ai_coverage")})))
    db.set_setting("current_digest", d["content_hash"])


def load_digest(content_hash: str | None = None) -> dict | None:
    h = content_hash or db.get_setting("current_digest")
    row = db.one("SELECT * FROM digests WHERE content_hash=?", (h,)) if h else None
    if not row:
        return None
    extra = json.loads(row["model_log_json"])
    return {"content_hash": row["content_hash"], "created_at": row["created_at"], "record_count": row["record_count"],
            "snapshot": json.loads(row["snapshot_json"]), "kpis": json.loads(row["kpis_json"]), "stage": json.loads(row["stage_json"]),
            "timeline": json.loads(row["timeline_json"]), "top10": json.loads(row["top10_json"]),
            "attention": json.loads(row["attention_json"]), "injuries": json.loads(row["injuries_json"]),
            "contact": json.loads(row["contact_json"]), "waterfall": json.loads(row["waterfall_json"]),
            "facts": json.loads(row["facts_json"]), **extra}


def emit_changes(prev: dict | None, cur: dict) -> None:
    if not prev:
        return
    diff = code_agents.detect_changes(prev, cur)
    with db.tx() as c:
        for it in diff["items"][:30]:
            visible = 1 if it["kind"] == "stage" else 0
            c.execute("INSERT INTO change_events(created_at,kind,summary,source_ref,provider_visible,digest_hash) VALUES(?,?,?,?,?,?)",
                      (db.now_iso(), it["kind"], it["summary"], json.dumps(it.get("source")), visible, cur["content_hash"]))



def run_pipeline(force: bool = False) -> dict:
    """Sync from Clio and (re)build the digest if the content hash changed."""
    if not _run_lock.acquire(blocking=False):
        return {"status": "already running"}
    _status.update(running=True, error=None, started_at=db.now_iso(), finished_at=None)
    try:
        _progress("Reading the matter from Clio (GET only)")
        bundle = fetch_bundle()
        res = ingest(bundle, progress=_progress)
        h = res["content_hash"]
        prev = load_digest()
        if not force and db.one("SELECT 1 FROM digests WHERE content_hash=?", (h,)):
            db.set_setting("current_digest", h)
            _progress("No changes in Clio; cached digest reused")
            return {"status": "cached", "content_hash": h}
        _cleanup_orphans()
        stats = run_extraction(progress=_progress)
        vstats = run_verifier(progress=_progress)
        d = build_digest(h)
        d["pipeline_stats"] = {"extraction": stats, "verifier": vstats}
        save_digest(d)
        emit_changes(prev, d)
        _progress("Updating shared provider links")
        try:  # every live provider link picks up changed, new or withdrawn items
            from . import sharing
            sharing.refresh_links(d)
        except Exception:
            traceback.print_exc()
        _progress("Building Case X-Ray")
        try:  # X-Ray is additive: a failure here never blocks the digest
            from .xray import service as xray_service
            xray_service.build(d)
        except Exception:
            traceback.print_exc()
        _progress("Digest ready")
        return {"status": "built", "content_hash": h, "extraction": stats, "verifier": vstats}
    except Exception as e:  # surfaced in the UI
        _status["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        raise
    finally:
        _status.update(running=False, finished_at=db.now_iso())
        _run_lock.release()


def run_in_background(force: bool = False) -> None:
    def target():
        try:
            run_pipeline(force)
        except Exception:
            pass
    threading.Thread(target=target, daemon=True).start()
