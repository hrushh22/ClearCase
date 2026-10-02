"""Provider share links: server-side allowlist, signed claims, expiry, revocation, access log, live refresh.

The provider endpoint returns ONLY claims the attorney approved, as signed packages. Nothing is
filtered in the frontend; unapproved data never leaves the server.

Live updates: every claim on a link has a stable key (e.g. "stage", "bill_mccullochortho", "need_<task id>").
After each sync, `refresh_links` re-derives that provider's items from the new digest:
  * an approved item whose text changed is re-signed; the old version is retired (superseded)
  * an approved item that no longer applies (e.g. the request was completed) is withdrawn
  * NEW items appear automatically only in the low-risk categories the attorney already shared
    (status, what the firm needs, visits, the office's own bill); anything else needs a new share
Each change is written to that link's update feed, and subscribers are emailed (or a mocked email is logged).
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from . import db
from .agents.share_policy import build_candidates, provider_contacts
from .config import env, firm_name
from .scenario import provider_waterfall, waterfall_text
from .signing import public_key_b64, sign_claim

AUTO_CATEGORIES = {"status", "needs", "treatment", "bills"}  # new items in these flow to an approved link automatically


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _case_ref(digest: dict) -> str:
    return f"{digest['snapshot'].get('display_number') or digest['snapshot']['matter_id']}"


def _items(digest: dict, provider: dict) -> dict[str, dict]:
    """Everything this provider could be shown right now, by stable key: {key: {text, category, source_hash}}."""
    items = {c["id"]: {"text": c["text"], "category": c["category"], "source_hash": c["source_hash"]}
             for c in build_candidates(digest, provider)}
    wt = waterfall_text(provider_waterfall(digest, provider))
    if wt:
        text, row = wt
        items["waterfall_position"] = {"text": text, "category": "bills", "row": row,
                                       "source_hash": hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()}
    return items


def _insert_claim(c, token: str, key: str, item: dict, case_ref: str, expires: str) -> None:
    signed = sign_claim(item["text"], case_ref, item["source_hash"], expires)
    c.execute("INSERT INTO share_claims(id,share_token,claim_text,payload_json,source_hash,signature,issued_at,expires_at,category,claim_key,superseded) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,0)", (f"{token[:8]}_{key}_{secrets.token_hex(3)}", token, signed["package"]["claim"], signed["payload"],
                                               signed["package"]["source_hash"], signed["signature"], signed["package"]["issued_at"], expires,
                                               item["category"], key))


def _event(c, token: str, summary: str, kind: str = "provider_update") -> None:
    c.execute("INSERT INTO change_events(created_at,kind,summary,source_ref,provider_visible,share_token) VALUES(?,?,?,?,1,?)",
              (db.now_iso(), kind, summary, None, token))


def create_link(digest: dict, provider_id: str, approved_ids: list[str], days: int = 30, waterfall: dict | None = None) -> dict:
    providers = {p["id"]: p for p in provider_contacts(db.get_setting("bundle", {}))}
    provider = providers.get(provider_id)
    if not provider:
        raise ValueError("Unknown provider")
    # re-derive items server-side; the client only sends ids, never claim text
    items = _items(digest, provider)
    approved = {k: items[k] for k in approved_ids if k in items}
    token = secrets.token_urlsafe(18)
    expires = (_now() + timedelta(days=days)).isoformat()
    categories = sorted({v["category"] for v in approved.values()})
    wf = approved.get("waterfall_position", {}).get("row")
    with db.tx() as c:
        c.execute("INSERT INTO share_links(token,provider_name,created_at,expires_at,allowed_claims_json,revoked) VALUES(?,?,?,?,?,0)",
                  (token, provider["name"], _now().isoformat(), expires,
                   json.dumps({"provider_id": provider_id, "approved_ids": list(approved), "waterfall": wf, "categories": categories,
                               "auto_categories": sorted(AUTO_CATEGORIES & set(categories))})))
        for key, item in approved.items():
            _insert_claim(c, token, key, item, _case_ref(digest), expires)
    return {"token": token, "expires_at": expires, "claims": len(approved)}


def _active_claims(token: str) -> list[dict]:
    return db.query("SELECT id, claim_key, claim_text, payload_json, signature, issued_at, category FROM share_claims "
                    "WHERE share_token=? AND COALESCE(superseded,0)=0 ORDER BY issued_at", (token,))


def refresh_links(digest: dict) -> dict:
    """Bring every live link up to date with the latest digest. Returns {token: [change summaries]}."""
    providers = {p["id"]: p for p in provider_contacts(db.get_setting("bundle", {}))}
    report: dict[str, list[str]] = {}
    for link in db.query("SELECT * FROM share_links WHERE revoked=0 AND expires_at>?", (_now().isoformat(),)):
        allowed = json.loads(link["allowed_claims_json"] or "{}")
        provider = providers.get(allowed.get("provider_id"))
        if not provider:
            continue
        items = _items(digest, provider)
        auto = set(allowed.get("auto_categories") or (AUTO_CATEGORIES & set(allowed.get("categories", []))))
        approved = set(allowed.get("approved_ids", []))
        wanted = approved | {k for k, v in items.items() if v["category"] in auto}
        current = {c["claim_key"]: c for c in _active_claims(link["token"])}
        changes: list[str] = []
        with db.tx() as c:
            for key in sorted(wanted | set(current)):
                item, cur = items.get(key), current.get(key)
                if key not in wanted:
                    continue
                if item is None:
                    if cur:  # no longer true or no longer needed: withdraw it
                        c.execute("UPDATE share_claims SET superseded=1 WHERE id=?", (cur["id"],))
                        changes.append(f"No longer applies: {cur['claim_text']}")
                    continue
                if cur and cur["claim_text"] == item["text"]:
                    continue
                if cur:
                    c.execute("UPDATE share_claims SET superseded=1 WHERE id=?", (cur["id"],))
                _insert_claim(c, link["token"], key, item, _case_ref(digest), link["expires_at"])
                changes.append(("Updated: " if cur else "New: ") + item["text"])
            for ch in changes:
                _event(c, link["token"], ch)
            if changes:
                allowed["approved_ids"] = sorted(approved | {k for k in wanted if k in items})
                if "waterfall_position" in items and "waterfall_position" in wanted:
                    allowed["waterfall"] = items["waterfall_position"]["row"]
                allowed["categories"] = sorted(set(allowed.get("categories", [])) | {items[k]["category"] for k in wanted if k in items})
                c.execute("UPDATE share_links SET allowed_claims_json=? WHERE token=?", (json.dumps(allowed), link["token"]))
        if changes:
            report[link["token"]] = changes
            if link.get("notify_email"):
                send_email(link["notify_email"], f"Case update from {firm_name()}",
                           "\n".join(changes[:10]) + "\n\nOpen your ClearCase link for the signed details.")
    return report


def on_stage_change(digest: dict) -> None:  # kept for callers; stage changes are covered by refresh_links
    refresh_links(digest)


def list_links() -> list[dict]:
    rows = db.query("SELECT * FROM share_links ORDER BY created_at DESC")
    for r in rows:
        r["allowed"] = json.loads(r.pop("allowed_claims_json") or "{}")
        r["opens"] = db.query("SELECT opened_at, ip_hash, user_agent FROM access_log WHERE token=? ORDER BY opened_at DESC", (r["token"],))
        r["claim_count"] = len(_active_claims(r["token"]))
        r["updates"] = db.query("SELECT created_at, summary FROM change_events WHERE share_token=? ORDER BY id DESC LIMIT 20", (r["token"],))
    return rows


def revoke(token: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE share_links SET revoked=1 WHERE token=?", (token,))


def provider_view(token: str, ip: str, user_agent: str, poll: bool = False) -> dict:
    """What the provider sees. `poll=True` = the page's own background refresh: not logged as a new open."""
    link = db.one("SELECT * FROM share_links WHERE token=?", (token,))
    if not link:
        return {"error": "not_found"}
    if not poll:
        with db.tx() as c:
            c.execute("INSERT INTO access_log(token,opened_at,ip_hash,user_agent) VALUES(?,?,?,?)",
                      (token, db.now_iso(), hashlib.sha256(ip.encode()).hexdigest()[:12], (user_agent or "")[:160]))
    if link["revoked"]:
        return {"error": "revoked", "firm_name": firm_name()}
    if link["expires_at"] < _now().isoformat():
        return {"error": "expired", "firm_name": firm_name()}
    allowed = json.loads(link["allowed_claims_json"] or "{}")
    claims = _active_claims(token)
    events = db.query("SELECT created_at, summary FROM change_events WHERE share_token=? ORDER BY id DESC LIMIT 50", (token,))
    return {"firm_name": firm_name(), "provider_name": link["provider_name"], "created_at": link["created_at"],
            "expires_at": link["expires_at"], "public_key": public_key_b64(),
            "claims": [{"id": c["id"], "key": c["claim_key"], "category": c["category"], "payload": c["payload_json"],
                        "signature": c["signature"]} for c in claims],
            "updated_at": max([c["issued_at"] for c in claims] or [link["created_at"]]),
            "categories": allowed.get("categories", []), "waterfall": allowed.get("waterfall"), "events": events,
            "notify_email": link.get("notify_email"), "auto_categories": allowed.get("auto_categories", [])}


def subscribe(token: str, email: str) -> dict:
    link = db.one("SELECT revoked, expires_at FROM share_links WHERE token=?", (token,))
    if not link or link["revoked"]:
        return {"ok": False}
    with db.tx() as c:
        c.execute("UPDATE share_links SET notify_email=? WHERE token=?", (email, token))
    return {"ok": True, "email_mode": "resend" if env("RESEND_API_KEY") else "mocked (in-app feed only; no RESEND_API_KEY)"}


def send_email(to: str, subject: str, text: str) -> str:
    key = env("RESEND_API_KEY")
    if not key:
        with db.tx() as c:
            c.execute("INSERT INTO change_events(created_at,kind,summary,source_ref,provider_visible) VALUES(?,?,?,?,0)",
                      (db.now_iso(), "email_mocked", f"[mocked email to {to}] {subject}", None))
        return "mocked"
    httpx.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {key}"}, timeout=20,
               json={"from": env("NOTIFY_EMAIL_FROM") or "onboarding@resend.dev", "to": [to], "subject": subject, "text": text})
    return "sent"
