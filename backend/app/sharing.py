"""Provider share links: server-side allowlist, signed claims, expiry, revocation, access log.

The provider endpoint returns ONLY claims the attorney approved, as signed packages. Nothing is
filtered in the frontend; unapproved data never leaves the server.
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
from .signing import public_key_b64, sign_claim


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def create_link(digest: dict, provider_id: str, approved_ids: list[str], days: int = 30, waterfall: dict | None = None) -> dict:
    providers = {p["id"]: p for p in provider_contacts(db.get_setting("bundle", {}))}
    provider = providers.get(provider_id)
    if not provider:
        raise ValueError("Unknown provider")
    # re-derive candidates server-side; the client only sends ids, never claim text
    cands = {c["id"]: c for c in build_candidates(digest, provider)}
    approved = [cands[i] for i in approved_ids if i in cands]
    token = secrets.token_urlsafe(18)
    expires = (_now() + timedelta(days=days)).isoformat()
    case_ref = f"{digest['snapshot'].get('display_number') or digest['snapshot']['matter_id']}"
    claims = []
    for c in approved:
        signed = sign_claim(c["text"], case_ref, c["source_hash"], expires)
        claims.append({"id": f"{token[:8]}_{c['id']}", "category": c["category"], **signed})
    wf = None
    if waterfall and "waterfall_position" in approved_ids:
        mine = [r for r in waterfall.get("liens", []) if r.get("mine")]
        if mine:
            r = mine[0]
            text = (f"Your office's balance of ${r['billed']:,.2f} is number {r['position']} of {waterfall.get('count')} in the payment line "
                    f"under the firm's current working scenario.")
            signed = sign_claim(text, case_ref, hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest(), expires)
            claims.append({"id": f"{token[:8]}_waterfall", "category": "bills", **signed})
            wf = {"billed": r["billed"], "net": r["net"], "position": r["position"], "count": waterfall.get("count"),
                  "status": r.get("status")}
    with db.tx() as c:
        c.execute("INSERT INTO share_links(token,provider_name,created_at,expires_at,allowed_claims_json,revoked) VALUES(?,?,?,?,?,0)",
                  (token, provider["name"], _now().isoformat(), expires,
                   json.dumps({"provider_id": provider_id, "approved_ids": approved_ids, "waterfall": wf,
                               "categories": sorted({x["category"] for x in approved})})))
        for cl in claims:
            c.execute("INSERT INTO share_claims(id,share_token,claim_text,payload_json,source_hash,signature,issued_at,expires_at,category) "
                      "VALUES(?,?,?,?,?,?,?,?,?)", (cl["id"], token, cl["package"]["claim"], cl["payload"], cl["package"]["source_hash"],
                                                    cl["signature"], cl["package"]["issued_at"], expires, cl["category"]))
    return {"token": token, "expires_at": expires, "claims": len(claims)}


def list_links() -> list[dict]:
    rows = db.query("SELECT * FROM share_links ORDER BY created_at DESC")
    for r in rows:
        r["allowed"] = json.loads(r.pop("allowed_claims_json") or "{}")
        r["opens"] = db.query("SELECT opened_at, ip_hash, user_agent FROM access_log WHERE token=? ORDER BY opened_at DESC", (r["token"],))
        r["claim_count"] = (db.one("SELECT COUNT(*) n FROM share_claims WHERE share_token=?", (r["token"],)) or {}).get("n", 0)
    return rows


def revoke(token: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE share_links SET revoked=1 WHERE token=?", (token,))


def provider_view(token: str, ip: str, user_agent: str) -> dict:
    link = db.one("SELECT * FROM share_links WHERE token=?", (token,))
    if not link:
        return {"error": "not_found"}
    with db.tx() as c:
        c.execute("INSERT INTO access_log(token,opened_at,ip_hash,user_agent) VALUES(?,?,?,?)",
                  (token, db.now_iso(), hashlib.sha256(ip.encode()).hexdigest()[:12], (user_agent or "")[:160]))
    if link["revoked"]:
        return {"error": "revoked", "firm_name": firm_name()}
    if link["expires_at"] < _now().isoformat():
        return {"error": "expired", "firm_name": firm_name()}
    allowed = json.loads(link["allowed_claims_json"] or "{}")
    claims = db.query("SELECT id, claim_text, payload_json, signature, issued_at, expires_at, category FROM share_claims WHERE share_token=? "
                      "ORDER BY issued_at", (token,))
    events = []
    if "status" in allowed.get("categories", []):
        events = db.query("SELECT created_at, summary FROM change_events WHERE provider_visible=1 AND created_at>=? ORDER BY created_at DESC",
                          (link["created_at"],))
    return {"firm_name": firm_name(), "provider_name": link["provider_name"], "created_at": link["created_at"],
            "expires_at": link["expires_at"], "public_key": public_key_b64(),
            "claims": [{"id": c["id"], "category": c["category"], "payload": c["payload_json"], "signature": c["signature"]} for c in claims],
            "categories": allowed.get("categories", []), "waterfall": allowed.get("waterfall"), "events": events,
            "notify_email": link.get("notify_email")}


def subscribe(token: str, email: str) -> dict:
    link = db.one("SELECT revoked, expires_at FROM share_links WHERE token=?", (token,))
    if not link or link["revoked"]:
        return {"ok": False}
    with db.tx() as c:
        c.execute("UPDATE share_links SET notify_email=? WHERE token=?", (email, token))
    return {"ok": True, "email_mode": "resend" if env("RESEND_API_KEY") else "mocked (in-app feed only; no RESEND_API_KEY)"}


def on_stage_change(digest: dict) -> None:
    """Re-issue a signed stage claim on every live link that shares status, and notify subscribers."""
    st = digest["stage"]
    for link in db.query("SELECT * FROM share_links WHERE revoked=0 AND expires_at>?", (_now().isoformat(),)):
        allowed = json.loads(link["allowed_claims_json"] or "{}")
        if "stage" not in allowed.get("approved_ids", []) or not st.get("evidence"):
            continue
        from .agents.share_policy import source_hash
        ev = st["evidence"][0]
        signed = sign_claim(f"Current stage: {st['stage']}.", digest["snapshot"].get("display_number") or "",
                            source_hash(ev["source_type"], ev["source_id"], ev.get("page")), link["expires_at"])
        with db.tx() as c:
            c.execute("INSERT INTO share_claims(id,share_token,claim_text,payload_json,source_hash,signature,issued_at,expires_at,category) "
                      "VALUES(?,?,?,?,?,?,?,?,?)", (f"{link['token'][:8]}_stage_{secrets.token_hex(3)}", link["token"],
                                                    signed["package"]["claim"], signed["payload"], signed["package"]["source_hash"],
                                                    signed["signature"], signed["package"]["issued_at"], link["expires_at"], "status"))
        if link.get("notify_email"):
            send_email(link["notify_email"], f"Case update from {firm_name()}", f"The case moved to: {st['stage']}. Open your link for details.")


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
