"""X-Ray orchestration: build, verify, persist lifecycle, cache by content hash, spotlight, time travel, actions."""
from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta

from .. import db
from . import contradictions, gaps, graph, stress_test
from .common import SEVERITY_RANK, documents, load_facts, today
from .evidence_quality import injury_map, propositions

SCHEMA = """
CREATE TABLE IF NOT EXISTS case_issues(
  id TEXT PRIMARY KEY, content_hash TEXT, issue_type TEXT, severity TEXT, title TEXT, explanation TEXT,
  related_fact_ids_json TEXT, evidence_for_json TEXT, evidence_against_json TEXT, suggested_action TEXT,
  confidence REAL, verify_status TEXT, first_detected_at TEXT, updated_at TEXT, resolved_at TEXT, reopened_at TEXT,
  payload_json TEXT);
CREATE TABLE IF NOT EXISTS evidence_edges(
  id TEXT, content_hash TEXT, source_node_type TEXT, source_node_id TEXT, target_node_type TEXT, target_node_id TEXT,
  relationship TEXT, confidence REAL, verify_status TEXT, source_fact_ids_json TEXT, PRIMARY KEY(content_hash, id));
CREATE TABLE IF NOT EXISTS issue_actions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT, action_type TEXT, content TEXT, status TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS xray_cache(content_hash TEXT PRIMARY KEY, created_at TEXT, payload_json TEXT, impact_json TEXT);
CREATE TABLE IF NOT EXISTS xray_stress(content_hash TEXT PRIMARY KEY, created_at TEXT, payload_json TEXT);
"""


def init() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


# ------------------------------------------------------------------ verification (rule 17)

def verify_issues(issues: list[dict], facts: list[dict]) -> list[dict]:
    """Referenced facts must exist and be visible. Partial / AI-paired / thin findings -> needs_review."""
    by_id = {f["fact_id"]: f for f in facts}
    sources = {(r["source_type"], r["source_id"]) for r in db.query("SELECT source_type, source_id FROM sources")}
    doc_ids = {r["id"] for r in db.query("SELECT id FROM documents")}
    out = []
    for i in issues:
        ids = i.get("related_fact_ids") or []
        if any(x not in by_id for x in ids):
            continue  # cites a fact that is unsupported or gone: hidden
        refs_ok = all((e["source_type"], e["source_id"]) in sources or (e["source_type"] == "document" and e["source_id"] in doc_ids)
                      for e in i.get("evidence_for", []))
        if not refs_ok or (not ids and not i.get("evidence_for")):
            continue
        statuses = {by_id[x]["verify_status"] for x in ids}
        needs = (statuses - {"supported"}) or i.get("method") == "llm" or i.get("kind") in ("sequence", "chronology")
        out.append({**i, "verify_status": "needs_review" if needs else "verified"})
    return out


# ------------------------------------------------------------------------ spotlight

def spotlight(issues: list[dict], new_ids: set[str]) -> list[dict]:
    """Deterministic ranking: severity, unresolved, deadline, money, facts affected, confidence, recency."""
    t = today()
    soon = (date.today() + timedelta(days=14)).isoformat()
    ranked = []
    for i in issues:
        if i.get("review", {}).get("status") in ("resolved", "snoozed", "explained"):
            continue
        money = max([float(x) for x in re.findall(r"\$([0-9][0-9,]*)", i["explanation"].replace(",", ""))] or [0])
        due = i.get("due")
        parts = {"severity": SEVERITY_RANK[i["severity"]] * 10, "unresolved": 5,
                 "deadline": 6 if due and due < t else 4 if due and due <= soon else 0,
                 "money": round(math.log10(money), 1) if money > 1 else 0, "facts": min(len(i.get("related_fact_ids") or []), 4),
                 "confidence": 2 if i["verify_status"] == "verified" else 0, "new": 5 if i["id"] in new_ids else 0}
        why = {"contradiction": "Two sources in the file disagree; opposing counsel can use either.",
               "amount_mismatch": "Amounts disagree; damages figures must reconcile before a demand.",
               "dependency": "Something the case needs is waiting on another party.",
               "missing_evidence": "Expected supporting material is not in the file.",
               "timeline_gap": "The chronology has a hole or an entry out of order."}.get(i["issue_type"], "Needs attorney review.")
        ranked.append({"issue_id": i["id"], "score": round(sum(parts.values()), 1), "components": parts, "why": why})
    ranked.sort(key=lambda r: (-r["score"], r["issue_id"]))
    return ranked[:8]


# --------------------------------------------------------------------------- build

def _titles() -> dict:
    t = {(r["source_type"], r["source_id"]): r["title"] for r in db.query("SELECT source_type, source_id, title FROM sources")}
    t.update({("document", r["id"]): r["name"] for r in db.query("SELECT id, name FROM documents")})
    return t


def compute(as_of: str | None = None, use_llm: bool = True, digest: dict | None = None) -> dict:
    from ..digest import load_digest

    init()
    d = digest or load_digest() or {}
    bundle = db.get_setting("bundle", {}) or {}
    facts = load_facts(as_of)
    docs = documents(as_of)
    llm_pairs = None
    if as_of:  # time travel reuses persisted AI pairs instead of calling the model on every slider move
        cached = latest()
        llm_pairs = [i for i in (cached or {}).get("issues", []) if i.get("method") == "llm"]
    contra = contradictions.detect(facts, use_llm=use_llm and not as_of, llm_pairs=llm_pairs)
    gap_issues, chain = gaps.detect(facts, docs, bundle, d.get("attention"), include_dependencies=not as_of)
    issues = verify_issues(contra + gap_issues, facts)
    injury = injury_map(facts, issues)
    props = propositions(facts, issues, injury, d.get("kpis"))
    prev = latest()
    prev_fact_ids = set((prev or {}).get("fact_ids", []))
    new_fact_ids = {f["fact_id"] for f in facts} - prev_fact_ids if prev and not as_of else set()
    g = graph.build(facts, props, issues, injury, bundle, docs, new_fact_ids, _titles())
    attach_reviews(issues)
    counts = {"contradictions": sum(i["issue_type"] in ("contradiction", "amount_mismatch") for i in issues),
              "gaps": sum(i["issue_type"] in ("missing_evidence", "timeline_gap") for i in issues),
              "dependencies": sum(i["issue_type"] == "dependency" for i in issues),
              "needs_review": sum(i["verify_status"] == "needs_review" for i in issues)}
    return {"content_hash": d.get("content_hash"), "as_of": as_of, "generated_at": db.now_iso(),
            "verified_fact_count": sum(f["verify_status"] == "supported" for f in facts), "fact_count": len(facts),
            "issues": sorted(issues, key=lambda i: (-SEVERITY_RANK[i["severity"]], i["issue_type"], i["title"])),
            "counts": counts, "total": len(issues), "propositions": props, "injury": injury, "gap_chain": chain, "graph": g,
            "fact_ids": [f["fact_id"] for f in facts], "spotlight": spotlight(issues, set()),
            "incident_date": (contradictions.incident_date(facts) or {}).get("date")}


def _persist_lifecycle(x: dict) -> dict:
    """first detected / updated / resolved / reopened, keyed by stable issue ids."""
    now = db.now_iso()
    existing = {r["id"]: r for r in db.query("SELECT id, resolved_at, first_detected_at FROM case_issues")}
    current = {i["id"] for i in x["issues"]}
    impact = {"new": [], "resolved": [], "reopened": [], "supporting_facts_added": 0}
    with db.tx() as c:
        for i in x["issues"]:
            row = existing.get(i["id"])
            payload = json.dumps(i)
            if not row:
                c.execute("INSERT INTO case_issues(id,content_hash,issue_type,severity,title,explanation,related_fact_ids_json,evidence_for_json,"
                          "evidence_against_json,suggested_action,confidence,verify_status,first_detected_at,updated_at,payload_json) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (i["id"], x["content_hash"], i["issue_type"], i["severity"], i["title"], i["explanation"],
                           json.dumps(i["related_fact_ids"]), json.dumps(i["evidence_for"]), json.dumps(i["evidence_against"]),
                           i["suggested_action"], i["confidence"], i["verify_status"], now, now, payload))
                if existing:
                    impact["new"].append(i["id"])
            else:
                reopened = row["resolved_at"] is not None
                c.execute("UPDATE case_issues SET content_hash=?, verify_status=?, updated_at=?, payload_json=?, resolved_at=NULL"
                          + (", reopened_at=?" if reopened else "") + " WHERE id=?",
                          (x["content_hash"], i["verify_status"], now, payload, *( [now] if reopened else []), i["id"]))
                if reopened:
                    impact["reopened"].append(i["id"])
        for iid, row in existing.items():
            if iid not in current and row["resolved_at"] is None:
                c.execute("UPDATE case_issues SET resolved_at=?, updated_at=? WHERE id=?", (now, now, iid))
                impact["resolved"].append(iid)
        c.execute("DELETE FROM evidence_edges WHERE content_hash=?", (x["content_hash"],))
        types = {n["id"]: n["type"] for n in x["graph"]["nodes"]}
        for e in x["graph"]["edges"]:
            c.execute("INSERT OR REPLACE INTO evidence_edges VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (e["id"], x["content_hash"], types.get(e["source"]), e["source"], types.get(e["target"]), e["target"],
                       e["relationship"], 0.6 if e["method"] == "llm" else 1.0, e["verify_status"], json.dumps(e["source_fact_ids"])))
    resolved_rows = db.query(f"SELECT id, title, issue_type FROM case_issues WHERE id IN ({','.join('?' * len(impact['resolved']))})",
                             impact["resolved"]) if impact["resolved"] else []
    impact["resolved_titles"] = [r["title"] for r in resolved_rows]
    return impact


def build(digest: dict | None = None, force: bool = False) -> dict:
    """Build (or reuse) the X-Ray for the current content hash. Called after the digest pipeline."""
    from ..digest import load_digest

    init()
    d = digest or load_digest()
    if not d:
        raise ValueError("No digest yet")
    if not force:
        row = db.one("SELECT payload_json FROM xray_cache WHERE content_hash=?", (d["content_hash"],))
        if row:
            return json.loads(row["payload_json"])
    prev = latest()
    x = compute(digest=d)
    prev_ids = set((prev or {}).get("fact_ids", []))
    impact = _persist_lifecycle(x)
    impact["supporting_facts_added"] = len(set(x["fact_ids"]) - prev_ids) if prev else 0
    impact["new_contradictions"] = sum(1 for i in x["issues"] if i["id"] in impact["new"] and i["issue_type"] in ("contradiction", "amount_mismatch"))
    impact["new_gaps"] = sum(1 for i in x["issues"] if i["id"] in impact["new"] and i["issue_type"] != "contradiction")
    impact["compared_to"] = (prev or {}).get("content_hash")
    x["impact"] = impact
    x["spotlight"] = spotlight(x["issues"], set(impact["new"]))
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO xray_cache(content_hash,created_at,payload_json,impact_json) VALUES(?,?,?,?)",
                  (d["content_hash"], x["generated_at"], json.dumps(x), json.dumps(impact)))
    db.set_setting("xray_latest", d["content_hash"])
    return x


def latest() -> dict | None:
    init()
    h = db.get_setting("xray_latest")
    row = db.one("SELECT payload_json FROM xray_cache WHERE content_hash=?", (h,)) if h else None
    return json.loads(row["payload_json"]) if row else None


def get(as_of: str | None = None) -> dict:
    """Cached X-Ray for the current digest (no LLM on load). With as_of: deterministic reconstruction, no LLM."""
    from ..digest import load_digest

    init()
    d = load_digest()
    if not d:
        raise ValueError("No digest yet")
    if as_of:
        x = compute(as_of=as_of, use_llm=False, digest=d)
        x["label"] = f"What the file showed as of {as_of}"
        return x
    row = db.one("SELECT payload_json FROM xray_cache WHERE content_hash=?", (d["content_hash"],))
    x = json.loads(row["payload_json"]) if row else build(d)
    attach_reviews(x["issues"])
    x["spotlight"] = spotlight(x["issues"], set((x.get("impact") or {}).get("new", [])))
    x["lifecycle"] = {r["id"]: r for r in db.query("SELECT id, first_detected_at, updated_at, resolved_at, reopened_at FROM case_issues")}
    return x


# ----------------------------------------------------------------------- actions

ACTIONS = {"draft_records_request", "draft_provider_followup", "internal_followup", "mark_reviewed", "snooze", "mark_resolved", "mark_explained"}
STATUS_FOR = {"mark_reviewed": "reviewed", "snooze": "snoozed", "mark_resolved": "resolved", "mark_explained": "explained"}


def attach_reviews(issues: list[dict]) -> None:
    init()
    rows = db.query("SELECT * FROM issue_actions ORDER BY id")
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["issue_id"], []).append(r)
    for i in issues:
        acts = by.get(i["id"], [])
        state = next((r for r in reversed(acts) if r["action_type"] in STATUS_FOR), None)
        i["review"] = {"status": STATUS_FOR[state["action_type"]] if state else "open", "at": state["created_at"] if state else None,
                       "note": state["content"] if state else None}
        i["actions"] = [{"id": r["id"], "type": r["action_type"], "content": r["content"], "status": r["status"], "created_at": r["created_at"]}
                        for r in acts]


def draft(issue: dict, kind: str) -> str:
    """Template drafts filled from the file. Never sent; the attorney copies them out."""
    from ..config import firm_name

    bundle = db.get_setting("bundle", {}) or {}
    client = next((c for c in bundle.get("contacts", []) if c.get("is_client")), {})
    who = issue.get("entity") or "your office"
    contact = next((c for c in bundle.get("contacts", []) if issue.get("entity") and c["name"] == issue["entity"]), {})
    refs = "\n".join(f"  - {e.get('text') or e.get('quote') or ''}".rstrip() for e in issue["evidence_for"][:4])
    dob = f" (DOB {client['date_of_birth']})" if client.get("date_of_birth") else ""
    if kind == "draft_records_request":
        return (f"To: {who}{(' <' + contact['email'] + '>') if contact.get('email') else ''}\n"
                f"Re: Records request - {client.get('name', 'our client')}{dob}\n\n"
                f"We represent {client.get('name', 'our client')} in a personal injury matter. A HIPAA authorization is on file.\n"
                f"Please provide: {issue['suggested_action'].rstrip('.')}.\n\nWhat our file currently shows:\n{refs}\n\n"
                f"Thank you,\n{firm_name()}")
    if kind == "draft_provider_followup":
        return (f"To: {who}\nRe: Follow-up - {client.get('name', 'our client')}{dob}\n\n"
                f"Following up on our earlier request. {issue['title']}.\n{issue['suggested_action']}\n\n"
                f"For reference:\n{refs}\n\nThank you,\n{firm_name()}")
    return f"Internal follow-up: {issue['title']}\nNext step: {issue['suggested_action']}\nEvidence:\n{refs}"


def add_action(issue_id: str, action_type: str, content: str | None = None) -> dict:
    init()
    if action_type not in ACTIONS:
        raise ValueError("unknown action")
    x = latest() or {}
    issue = next((i for i in x.get("issues", []) if i["id"] == issue_id), None)
    if not issue:
        row = db.one("SELECT payload_json FROM case_issues WHERE id=?", (issue_id,))
        issue = json.loads(row["payload_json"]) if row else None
    if not issue:
        raise KeyError(issue_id)
    if action_type.startswith("draft_") or action_type == "internal_followup":
        content = content or draft(issue, action_type)
        status = "draft"
    else:
        status = "done"
    now = db.now_iso()
    with db.tx() as c:
        cur = c.execute("INSERT INTO issue_actions(issue_id,action_type,content,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (issue_id, action_type, content, status, now, now))
    return {"id": cur.lastrowid, "issue_id": issue_id, "type": action_type, "content": content, "status": status, "created_at": now}


# -------------------------------------------------------------------- stress test

def stress(force: bool = False) -> dict:
    init()
    x = get()
    h = x["content_hash"]
    if not force:
        row = db.one("SELECT payload_json FROM xray_stress WHERE content_hash=?", (h,))
        if row:
            return {**json.loads(row["payload_json"]), "cached": True}
    out = stress_test.run(x["propositions"], x["issues"], load_facts())
    out["generated_at"] = db.now_iso()
    out["content_hash"] = h
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO xray_stress(content_hash,created_at,payload_json) VALUES(?,?,?)", (h, out["generated_at"], json.dumps(out)))
    return {**out, "cached": False}


def cached_stress() -> dict | None:
    init()
    x = latest()
    row = db.one("SELECT payload_json FROM xray_stress WHERE content_hash=?", ((x or {}).get("content_hash"),)) if x else None
    return json.loads(row["payload_json"]) if row else None
