"""ClearCase API. Run: uvicorn app.main:app --reload --port 8000 (from backend/)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import clio_auth, db, digest, sharing
from .agents import code_agents
from .agents.share_policy import mentions, propose, provider_contacts
from .config import ROOT, ConfigError, clio_source, firm_name
from .documents import find_page_for_quote
from .llm import available_providers, usage_report
from .signing import public_key_b64
from .scenario import ordered_liens as _ordered_liens, provider_waterfall
from .waterfall import DEFAULT_FEE_PCT, Lien, WaterfallInput, breakeven_gross, compute

app = FastAPI(title="ClearCase", version="1.0")
from .xray.routes import router as xray_router  # noqa: E402  (attorney-only Case X-Ray)

app.include_router(xray_router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ConfigError)
def _config_error(_: Request, exc: ConfigError):
    return JSONResponse(status_code=400, content={"error": "config", "detail": str(exc)})


def _digest_or_404() -> dict:
    d = digest.load_digest()
    if not d:
        raise HTTPException(404, "No digest yet. Press Sync to read the matter from Clio.")
    return d


# ------------------------------------------------------------------- status / sync

@app.get("/api/status")
def status():
    d = db.get_setting("current_digest")
    row = db.one("SELECT created_at, record_count FROM digests WHERE content_hash=?", (d,)) if d else None
    return {"pipeline": digest.status(), "last_sync": db.get_setting("last_sync"), "clio": {**clio_auth.status(), "source": clio_source()},
            "llm_providers": available_providers(), "digest": {"content_hash": d, **(row or {})}, "firm_name": firm_name()}


@app.post("/api/sync")
def sync(force: bool = False):
    digest.run_in_background(force)
    return {"started": True}


# ----------------------------------------------------------------------- attorney

@app.get("/api/digest")
def get_digest(user: str = "attorney"):
    """Cached digest + 'what changed since you last opened'. Never runs an LLM."""
    d = _digest_or_404()
    view = db.one("SELECT * FROM views WHERE user_id=?", (user,))
    compare_hash, since = None, None
    if view:
        if view["last_viewed_digest_hash"] != d["content_hash"]:
            compare_hash, since = view["last_viewed_digest_hash"], view["last_viewed_at"]
        else:  # this digest was already seen (e.g. a refresh): compare with the visit before
            compare_hash, since = view["previous_digest_hash"], view["previous_viewed_at"]
    prev = digest.load_digest(compare_hash) if compare_hash and compare_hash != d["content_hash"] else None
    changes = code_agents.detect_changes(prev, d) if prev else {"first_view": not view, "items": []}
    changes["since"] = since
    changes["last_viewed_at"] = since
    d["changes"] = changes
    return d


@app.post("/api/views/seen")
def mark_seen(user: str = "attorney"):
    d = _digest_or_404()
    view = db.one("SELECT * FROM views WHERE user_id=?", (user,))
    now = db.now_iso()
    with db.tx() as c:
        if view:
            # the visit being replaced becomes "previous", so a refresh still diffs against the real last visit
            c.execute("UPDATE views SET previous_digest_hash=last_viewed_digest_hash, previous_viewed_at=last_viewed_at, "
                      "last_viewed_digest_hash=?, last_viewed_at=? WHERE user_id=?", (d["content_hash"], now, user))
        else:
            c.execute("INSERT INTO views(user_id,last_viewed_digest_hash,last_viewed_at) VALUES(?,?,?)", (user, d["content_hash"], now))
    return {"ok": True, "at": now}


@app.get("/api/source/{source_type}/{source_id}")
def get_source(source_type: str, source_id: str):
    if source_type == "document":
        doc = db.one("SELECT id,name,folder,doc_type,page_count,scanned_pages,received_at FROM documents WHERE id=?", (source_id,))
        if not doc:
            raise HTTPException(404, "Document not found")
        return {"source_type": "document", **doc}
    row = db.one("SELECT * FROM sources WHERE source_type=? AND source_id=?", (source_type, source_id))
    if not row:
        raise HTTPException(404, "Source not found")
    row["meta"] = json.loads(row.pop("meta_json") or "{}")
    return row


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str):
    doc = db.one("SELECT name, local_path FROM documents WHERE id=?", (doc_id,))
    if not doc or not Path(doc["local_path"]).exists():
        raise HTTPException(404, "Document not found")
    return FileResponse(doc["local_path"], media_type="application/pdf", filename=doc["name"],
                        headers={"Content-Disposition": f'inline; filename="{doc["name"]}"'})


@app.get("/api/documents/{doc_id}/locate")
def locate(doc_id: str, quote: str, page: Optional[int] = None):
    """Page + highlight boxes for a quote. Falls back to the page without a box; never fails silently."""
    rows = db.query("SELECT page, text, words_json, method, width, height FROM doc_pages WHERE doc_id=? ORDER BY page", (doc_id,))
    if not rows:
        raise HTTPException(404, "Document has no pages")
    pages = [{"page": r["page"], "words": json.loads(r["words_json"])} for r in rows]
    found_page, res = find_page_for_quote(pages, quote, hint=page)
    target = found_page if res["bboxes"] else (page or found_page or 1)
    meta = rows[target - 1]
    return {"page": target, "bboxes": res["bboxes"] if found_page == target else [], "match": res["match"], "score": res["score"],
            "method": meta["method"], "width": meta["width"], "height": meta["height"],
            "note": None if res["bboxes"] else "Exact text not located on the page; opened the cited page without a highlight."}


@app.get("/api/documents/{doc_id}/pages/{page}")
def page_text(doc_id: str, page: int):
    row = db.one("SELECT text, method FROM doc_pages WHERE doc_id=? AND page=?", (doc_id, page))
    if not row:
        raise HTTPException(404)
    return row


@app.get("/api/events")
def events():
    return db.query("SELECT * FROM change_events ORDER BY created_at DESC LIMIT 100")


@app.get("/api/usage")
def usage():
    return usage_report()


# ---------------------------------------------------------------------- waterfall

class LienIn(BaseModel):
    name: str
    amount: float
    reduction: float = 0.0
    include: bool = True
    kind: str = "bill"


class WaterfallIn(BaseModel):
    gross: float
    fee_pct: float = DEFAULT_FEE_PCT
    liens: list[LienIn] = []
    expenses: list[float] | None = None
    save: bool = False


@app.get("/api/waterfall/settings")
def waterfall_settings():
    d = _digest_or_404()
    s = db.get_setting("waterfall", {}) or {}
    return {"fee_pct": s.get("fee_pct", DEFAULT_FEE_PCT), "gross": s.get("gross", d["waterfall"]["suggested_gross"]),
            "liens": [l.__dict__ for l in _ordered_liens(d, s)]}


@app.post("/api/waterfall")
def waterfall(inp: WaterfallIn):
    d = _digest_or_404()
    expenses = inp.expenses if inp.expenses is not None else [e["amount"] for e in d["waterfall"]["expenses"]]
    res = compute(WaterfallInput(gross=inp.gross, fee_pct=inp.fee_pct, expenses=expenses,
                                 liens=[Lien(**l.model_dump()) for l in inp.liens]))
    res["breakeven_gross"] = breakeven_gross(res["fee_pct"], res["costs"], res["lien_total"])
    if inp.save:
        db.set_setting("waterfall", {"fee_pct": inp.fee_pct, "gross": inp.gross, "order": [l.name for l in inp.liens],
                                     "liens": {l.name: {"reduction": l.reduction, "include": l.include} for l in inp.liens}})
        res["links_updated"] = len(sharing.refresh_links(d))  # a new scenario can move a provider's place in line
    return res


@app.post("/api/waterfall/reset")
def waterfall_reset():
    db.set_setting("waterfall", {})
    return waterfall_settings()


# ------------------------------------------------------------------------ sharing

@app.get("/api/providers")
def providers():
    return provider_contacts(db.get_setting("bundle", {}))


@app.get("/api/share/proposal/{provider_id}")
def share_proposal(provider_id: str):
    d = _digest_or_404()
    p = {x["id"]: x for x in provider_contacts(db.get_setting("bundle", {}))}.get(provider_id)
    if not p:
        raise HTTPException(404, "Unknown provider")
    out = propose(d, p)
    wf = provider_waterfall(d, p)
    if wf["liens"]:
        r = wf["liens"][0]
        out["candidates"].append({"id": "waterfall_position", "category": "bills", "suggested": "share",
                                  "reason": "This office's own balance and place in line; no other amounts.",
                                  "text": f"Your office's balance of ${r['billed']:,.2f} is number {r['position']} of {wf['count']} in the payment line "
                                          "under the firm's current working scenario.", "source": None})
    return out


class LinkIn(BaseModel):
    provider_id: str
    approved_ids: list[str]
    days: int = 30


@app.post("/api/share/links")
def create_link(inp: LinkIn):
    d = _digest_or_404()
    p = {x["id"]: x for x in provider_contacts(db.get_setting("bundle", {}))}.get(inp.provider_id)
    if not p:
        raise HTTPException(404, "Unknown provider")
    return sharing.create_link(d, inp.provider_id, inp.approved_ids, inp.days, provider_waterfall(d, p))


@app.get("/api/share/links")
def links():
    return sharing.list_links()


@app.post("/api/share/refresh")
def refresh_links():
    """Push the current digest to every live provider link now (also runs after every sync)."""
    return {"updated": sharing.refresh_links(_digest_or_404())}


@app.post("/api/share/links/{token}/revoke")
def revoke(token: str):
    sharing.revoke(token)
    return {"ok": True}


@app.get("/api/provider/{token}")
def provider_portal(token: str, request: Request, poll: bool = False):
    out = sharing.provider_view(token, request.client.host if request.client else "", request.headers.get("user-agent", ""), poll=poll)
    if out.get("error") == "not_found":
        raise HTTPException(404, "Link not found")
    return out


class SubIn(BaseModel):
    email: str


@app.post("/api/provider/{token}/subscribe")
def subscribe(token: str, inp: SubIn):
    return sharing.subscribe(token, inp.email)


@app.get("/.well-known/firm-key")
def firm_key():
    return {"alg": "Ed25519", "public_key": public_key_b64(), "firm": firm_name()}


# -------------------------------------------------------------------------- auth

@app.get("/auth/clio/login")
def clio_login():
    return RedirectResponse(clio_auth.authorize_url())


@app.get("/auth/clio/callback")
def clio_callback(code: str, state: str):
    clio_auth.exchange_code(code, state)
    return HTMLResponse("<p>Connected to Clio (read-only use). You can close this tab and press Sync in ClearCase.</p>")


# ----------------------------------------------------------------- built frontend
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith(("api/", "auth/", ".well-known/")):  # unknown API paths are 404s, never the app shell
            raise HTTPException(404, "Not found")
        return FileResponse(_dist / "index.html")
