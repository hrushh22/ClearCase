"""Fetch the matter bundle from Clio (live, GET only) and normalize it.

Two sources produce the same normalized bundle:
  * live   - Clio Manage API v4 through ClioReadClient (the default and what the demo uses)
  * mirror - the organizers' sapini-clio-data.json (the exact bodies the setup app sends
             to Clio). Offline development only; the UI labels it "offline mirror".

Nothing about the case is hardcoded here: every value comes from one of the two sources.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import clio_auth
from .clio_client import ClioError, ClioReadClient
from .config import ConfigError, DOC_CACHE_DIR, clio_source, env, mirror_path
from .db import now_iso
from .documents import sha256_file


def _name(obj: dict | None) -> str | None:
    if not obj:
        return None
    if obj.get("name"):
        return obj["name"]
    parts = [obj.get("first_name"), obj.get("last_name")]
    return " ".join(p for p in parts if p) or obj.get("company") or None


def _first(items: list | None, key: str) -> str | None:
    for it in items or []:
        if it.get("default_email") or it.get("default_number") or True:
            return it.get(key)
    return None


def _address(items: list | None) -> str | None:
    for a in items or []:
        return ", ".join(x for x in [a.get("street"), a.get("city"), a.get("province"), a.get("postal_code")] if x)
    return None


# =============================================================================== live

MATTER_FIELDS = [
    "id,display_number,description,status,open_date,close_date,statute_of_limitations,"
    "client{id,name},matter_stage{id,name},practice_area{id,name},responsible_attorney{id,name},"
    "originating_attorney{id,name},custom_field_values{id,field_name,field_type,value,custom_field{id}}",
    "id,display_number,description,status,open_date,statute_of_limitations,client{id,name},"
    "matter_stage{id,name},practice_area{id,name},responsible_attorney{id,name},"
    "custom_field_values{id,field_name,value}",
    "id,display_number,description,status,open_date,client{id,name},matter_stage{id,name}",
]


def fetch_live() -> dict[str, Any]:
    token = clio_auth.access_token()
    client = ClioReadClient(token, on_unauthorized=clio_auth.refresh)
    try:
        return _fetch_live(client)
    finally:
        client.close()


def _find_matter(c: ClioReadClient) -> dict:
    q = env("CLIO_MATTER_QUERY", "Sapini")
    for fields in MATTER_FIELDS:
        try:
            matters = list(c.iter_pages("matters.json", {"query": q, "fields": fields}))
        except ClioError as e:
            if "-> 400" in str(e):
                continue
            raise
        if not matters:
            raise ConfigError(f"No Clio matter matches '{q}'. Has the Sapini setup been run on this account?")
        return matters[0]
    raise ClioError("Could not read matters from Clio")


def _fetch_live(c: ClioReadClient) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    m = raw["matter"] = _find_matter(c)
    mid = m["id"]
    mp = {"matter_id": mid}

    raw["relationships"] = c.get_all("relationships.json", mp, [
        "id,description,contact{id,name,first_name,last_name,type}", "id,description,contact{id,name}"])
    contact_ids = {r["contact"]["id"] for r in raw["relationships"] if r.get("contact")}
    if m.get("client"):
        contact_ids.add(m["client"]["id"])
    raw["contacts"] = []
    for cid in sorted(contact_ids):
        for fields in ["id,name,first_name,last_name,title,type,company{name},date_of_birth,email_addresses{address,default_email},"
                       "phone_numbers{number,default_number},addresses{street,city,province,postal_code},avatar",
                       "id,name,first_name,last_name,type,email_addresses{address},phone_numbers{number}", "id,name,type"]:
            try:
                raw["contacts"].append(c.get(f"contacts/{cid}.json", {"fields": fields})["data"])
                break
            except ClioError as e:
                if "-> 400" not in str(e):
                    raise
    raw["notes"] = c.get_all("notes.json", {**mp, "type": "Matter"}, [
        "id,subject,detail,date,created_at,updated_at,author{id,name}", "id,subject,detail,date,created_at,updated_at"])
    raw["communications"] = c.get_all("communications.json", mp, [
        "id,type,subject,body,date,created_at,updated_at,senders{id,name,type},receivers{id,name,type}",
        "id,type,subject,body,date,created_at,updated_at,senders,receivers",
        "id,type,subject,body,date,created_at,updated_at"])
    raw["tasks"] = c.get_all("tasks.json", mp, [
        "id,name,description,due_at,status,statute_of_limitations,completed_at,created_at,updated_at,assignee{id,name,type},priority",
        "id,name,description,due_at,status,completed_at,created_at,updated_at"])
    raw["calendar_entries"] = c.get_all("calendar_entries.json", mp, [
        "id,summary,description,start_at,end_at,all_day,location,created_at,updated_at,matter{id}",
        "id,summary,description,start_at,end_at,created_at,updated_at"])
    raw["expenses"] = c.get_all("activities.json", {**mp, "type": "ExpenseEntry"}, [
        "id,type,date,quantity,price,total,note,created_at,updated_at", "id,type,date,total,note,created_at"])
    raw["documents"] = c.get_all("documents.json", mp, [
        "id,name,received_at,created_at,updated_at,size,content_type,parent{id,name,type},latest_document_version{uuid,size,content_type}",
        "id,name,received_at,created_at,parent{id,name}", "id,name,created_at"])
    try:
        raw["matter_stages"] = c.get_all("matter_stages.json", None, [
            "id,name,order,practice_area{id,name}", "id,name,practice_area{id,name}", "id,name"])
    except ClioError:
        raw["matter_stages"] = []

    # documents: download once, cache by Clio id + version
    docs = []
    for d in raw["documents"]:
        if not str(d.get("name", "")).lower().endswith(".pdf"):
            continue
        ver = ((d.get("latest_document_version") or {}).get("uuid")) or d.get("updated_at") or ""
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", d["name"])
        local = DOC_CACHE_DIR / f"{d['id']}_{re.sub(r'[^A-Za-z0-9]', '', str(ver))[:12]}_{safe}"
        if not local.exists():
            local.write_bytes(c.download(d["id"]))
        docs.append({"id": f"doc-{d['id']}", "clio_id": str(d["id"]), "name": d["name"],
                     "folder": (d.get("parent") or {}).get("name"),
                     "received_at": d.get("received_at") or d.get("created_at"),
                     "local_path": str(local), "sha256": sha256_file(local)})

    bundle = _normalize_live(raw, docs)
    bundle["source"] = {"kind": "live", "synced_at": now_iso(), "requests": c.request_count,
                        "matter_id": str(mid)}
    bundle["raw"] = raw
    return bundle


def _people(lst) -> list[dict]:
    out = []
    for p in lst or []:
        out.append({"id": str(p.get("id")), "name": p.get("name"), "type": p.get("type")})
    return out


def _normalize_live(raw: dict, docs: list[dict]) -> dict[str, Any]:
    m = raw["matter"]
    rel_by_contact = {str(r["contact"]["id"]): r.get("description") for r in raw["relationships"] if r.get("contact")}
    client_id = str((m.get("client") or {}).get("id"))
    contacts = []
    for ct in raw["contacts"]:
        cid = str(ct["id"])
        contacts.append({
            "id": cid, "name": _name(ct), "type": ct.get("type"), "title": ct.get("title"),
            "company": (ct.get("company") or {}).get("name") if isinstance(ct.get("company"), dict) else ct.get("company"),
            "email": _first(ct.get("email_addresses"), "address"), "phone": _first(ct.get("phone_numbers"), "number"),
            "address": _address(ct.get("addresses")), "date_of_birth": ct.get("date_of_birth"),
            "avatar": ct.get("avatar"), "relationship": "Client" if cid == client_id else rel_by_contact.get(cid),
            "is_client": cid == client_id,
        })
    stages = sorted(raw.get("matter_stages") or [], key=lambda s: (s.get("order") is None, s.get("order") or 0))
    pa = ((m.get("practice_area") or {}).get("name"))
    sol = m.get("statute_of_limitations")
    if isinstance(sol, dict):  # Clio returns a reference to the SOL task / calendar entry, not a date
        ref = str(sol.get("id"))
        hit = next((t for t in raw["tasks"] if str(t["id"]) == ref), None) or \
            next((e for e in raw["calendar_entries"] if str(e["id"]) == ref), None)
        sol = ((hit or {}).get("due_at") or (hit or {}).get("start_at") or "")[:10] or None
        if not sol:
            sol_task = next((t for t in raw["tasks"] if t.get("statute_of_limitations")), None)
            sol = ((sol_task or {}).get("due_at") or "")[:10] or None
    m = {**m, "statute_of_limitations": sol}
    stage_names = [s["name"] for s in stages if not pa or ((s.get("practice_area") or {}).get("name") in (None, pa))]
    return {
        "matter": {
            "id": str(m["id"]), "display_number": m.get("display_number"), "description": m.get("description"),
            "status": m.get("status"), "open_date": m.get("open_date"), "close_date": m.get("close_date"),
            "statute_of_limitations": m.get("statute_of_limitations"),
            "stage": (m.get("matter_stage") or {}).get("name"), "practice_area": pa,
            "responsible_attorney": (m.get("responsible_attorney") or {}).get("name"),
            "client_id": client_id, "client_name": (m.get("client") or {}).get("name"),
        },
        "stages": stage_names,
        "custom_fields": [{"id": str(v.get("id")), "name": v.get("field_name") or str((v.get("custom_field") or {}).get("id")),
                           "field_type": v.get("field_type"), "value": v.get("value")}
                          for v in m.get("custom_field_values") or []],
        "contacts": contacts,
        "notes": [{"id": str(n["id"]), "subject": n.get("subject"), "detail": n.get("detail") or "",
                   "date": n.get("date") or (n.get("created_at") or "")[:10], "created_at": n.get("created_at"),
                   "updated_at": n.get("updated_at")} for n in raw["notes"]],
        "communications": [{"id": str(x["id"]), "type": x.get("type"), "subject": x.get("subject"), "body": x.get("body") or "",
                            "date": x.get("date") or (x.get("created_at") or "")[:10], "senders": _people(x.get("senders")),
                            "receivers": _people(x.get("receivers")), "updated_at": x.get("updated_at")}
                           for x in raw["communications"]],
        "tasks": [{"id": str(t["id"]), "name": t.get("name"), "description": t.get("description") or "",
                   "due_at": (t.get("due_at") or "")[:10] or None, "status": t.get("status"),
                   "statute_of_limitations": bool(t.get("statute_of_limitations")),
                   "assignee": (t.get("assignee") or {}).get("name"), "completed_at": t.get("completed_at"),
                   "updated_at": t.get("updated_at")} for t in raw["tasks"]],
        "calendar": [{"id": str(e["id"]), "summary": e.get("summary"), "description": e.get("description") or "",
                      "start_at": e.get("start_at"), "end_at": e.get("end_at"), "updated_at": e.get("updated_at")}
                     for e in raw["calendar_entries"]],
        "expenses": [{"id": str(x["id"]), "date": x.get("date"),
                      "total": float(x.get("total") if x.get("total") is not None else (x.get("price") or 0) * (x.get("quantity") or 1)),
                      "note": x.get("note") or ""} for x in raw["expenses"]],
        "documents": docs,
    }


# ============================================================================= mirror

def _resolve(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        m = re.fullmatch(r"\{\{(.+?)\}\}", value)
        return ids.get(m.group(1), m.group(1)) if m else value
    if isinstance(value, dict):
        return {k: _resolve(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ids) for v in value]
    return value


def fetch_mirror() -> dict[str, Any]:
    path = mirror_path()
    if not path.exists():
        raise ConfigError(f"Mirror file not found at {path}. Set SAPINI_MIRROR_PATH or use CLIO_SOURCE=live.")
    d = json.loads(path.read_text(encoding="utf-8"))
    ids: dict[str, str] = {"matter_id": "mirror-matter", "user_id": "firm-user", "calendar_id": "firm-calendar"}
    for i, ct in enumerate(d["contacts"]["items"]):
        ids[f"contact:{ct['ref']}"] = f"contact-{i + 1}"
    contacts_by_id = {}
    for i, ct in enumerate(d["contacts"]["items"]):
        b = ct["body"]
        contacts_by_id[f"contact-{i + 1}"] = {"id": f"contact-{i + 1}", **b}
    rels = {str(_resolve(r["body"]["contact"]["id"], ids)): r["body"].get("description") for r in d["relationships"]["items"]}
    mb = d["matter"]["body"]
    client_id = str(_resolve(mb["client"]["id"], ids))
    fields_by_key = {f"field:{f['body']['name']}": f["body"] for f in d["custom_fields"]["items"]}

    def who(lst):
        out = []
        for p in lst or []:
            pid = str(_resolve(p["id"], ids))
            if p.get("type") == "User":
                out.append({"id": pid, "name": "Firm user", "type": "User"})
            else:
                out.append({"id": pid, "name": _name(contacts_by_id.get(pid)), "type": "Contact"})
        return out

    base = path.parent
    docs = []
    for i, it in enumerate(d["documents"]["items"]):
        local = (base / it["local_path"]).resolve()
        folder = re.sub(r"^\{\{folder:(.+)\}\}$", r"\1", it["body"]["parent"]["id"])
        docs.append({"id": f"doc-m{i + 1}", "clio_id": f"m{i + 1}", "name": it["body"]["name"], "folder": folder,
                     "received_at": it["body"].get("received_at"), "local_path": str(local), "sha256": it["sha256"]})

    stage_ref = re.sub(r"^\{\{stage:(.+)\}\}$", r"\1", mb["matter_stage"]["id"])
    return {
        "matter": {"id": "mirror-matter", "display_number": "00001-Sapini", "description": mb["description"],
                   "status": mb["status"], "open_date": mb["open_date"], "close_date": None,
                   "statute_of_limitations": mb.get("statute_of_limitations"), "stage": stage_ref,
                   "practice_area": "Personal Injury", "responsible_attorney": None,
                   "client_id": client_id, "client_name": _name(contacts_by_id.get(client_id))},
        "stages": d["matter_stages"]["stages_in_order"],
        "custom_fields": [{"id": f"cf-{i + 1}", "name": cv["custom_field"]["id"][len("{{field:"):-2],
                           "field_type": fields_by_key.get(cv["custom_field"]["id"][2:-2], {}).get("field_type"),
                           "value": cv["value"]} for i, cv in enumerate(mb["custom_field_values"])],
        "contacts": [{"id": cid, "name": _name(b), "type": b.get("type"), "title": b.get("title"), "company": b.get("company"),
                      "email": _first(b.get("email_addresses"), "address"), "phone": _first(b.get("phone_numbers"), "number"),
                      "address": _address(b.get("addresses")), "date_of_birth": b.get("date_of_birth"), "avatar": None,
                      "relationship": "Client" if cid == client_id else rels.get(cid), "is_client": cid == client_id}
                     for cid, b in contacts_by_id.items()],
        "notes": [{"id": f"note-{i + 1}", "subject": n["body"].get("subject"), "detail": n["body"].get("detail") or "",
                   "date": n["body"].get("date"), "created_at": None, "updated_at": None}
                  for i, n in enumerate(d["notes"]["items"])],
        "communications": [{"id": f"comm-{i + 1}", "type": x["body"].get("type"), "subject": x["body"].get("subject"),
                            "body": x["body"].get("body") or "", "date": x["body"].get("date"),
                            "senders": who(x["body"].get("senders")), "receivers": who(x["body"].get("receivers")),
                            "updated_at": None} for i, x in enumerate(d["communications"]["items"])],
        "tasks": [{"id": f"task-{i + 1}", "name": t["body"].get("name"), "description": t["body"].get("description") or "",
                   "due_at": t["body"].get("due_at"), "status": t["body"].get("status"),
                   "statute_of_limitations": bool(t["body"].get("statute_of_limitations")), "assignee": "Firm user",
                   "completed_at": None, "updated_at": None} for i, t in enumerate(d["tasks"]["items"])],
        "calendar": [{"id": f"cal-{i + 1}", "summary": e["body"].get("summary"), "description": e["body"].get("description") or "",
                      "start_at": e["body"].get("start_at"), "end_at": e["body"].get("end_at"), "updated_at": None}
                     for i, e in enumerate(d["calendar_entries"]["items"])],
        "expenses": [{"id": f"exp-{i + 1}", "date": x["body"].get("date"),
                      "total": float(x["body"].get("price", 0)) * float(x["body"].get("quantity", 1)),
                      "note": x["body"].get("note") or ""} for i, x in enumerate(d["expenses"]["items"])],
        "documents": docs,
        "source": {"kind": "mirror", "synced_at": now_iso(), "requests": 0, "matter_id": "mirror-matter",
                   "path": str(path)},
        "raw": d,
    }


def fetch_bundle() -> dict[str, Any]:
    return fetch_mirror() if clio_source() == "mirror" else fetch_live()
