"""Case X-Ray tests. Synthetic fixtures only (never Sapini findings)."""
import json

import pytest

from app import db
from app.xray import contradictions, gaps, graph, service
from app.xray.common import regions_in
from app.xray.evidence_quality import injury_map, propositions, support_state

DOI = {"fact_id": "f_doi", "type": "client_event", "text": "Date of Incident: 2024-03-01", "quote": "Date of Incident: 2024-03-01",
       "date": "2024-03-01", "known_at": "2024-03-01", "amount": None, "entity": None, "source_type": "custom_field",
       "source_id": "cf1", "page": None, "verify_status": "supported", "extractor": "structured"}


def fact(fid, ftype, text, quote=None, *, date=None, amount=None, entity=None, st="note", sid=None, status="supported", known="2024-05-01"):
    return {"fact_id": fid, "type": ftype, "text": text, "quote": quote or text, "date": date, "known_at": known, "amount": amount,
            "entity": entity, "source_type": st, "source_id": sid or f"src_{fid}", "page": 1 if st == "document" else None,
            "verify_status": status, "extractor": "llm"}


# ----------------------------------------------------------------- contradictions

def test_conflicting_incident_dates_detected():
    f = fact("f1", "client_event", "Accident date", "The accident occurred on 03/08/2024 at the intersection.")
    out = contradictions.detect([DOI, f], use_llm=False)
    assert any(i["kind"] == "date" and set(i["related_fact_ids"]) == {"f_doi", "f1"} for i in out)


def test_matching_incident_dates_ignored():
    f = fact("f1", "client_event", "Accident date", "The accident occurred on 03/01/2024 at the intersection.")
    assert not [i for i in contradictions.detect([DOI, f], use_llm=False) if i["kind"] == "date"]


def test_conflicting_lien_amounts_detected_and_equal_ignored():
    a = fact("l1", "lien", "Medicaid lien", "Medicaid lien of $20,000", amount=20000, entity="State Medicaid")
    b = fact("l2", "lien", "Medicaid lien", "Medicaid lien of $25,000", amount=25000, entity="State Medicaid")
    c = fact("l3", "lien", "Medicaid lien restated", "lien remains $20,000", amount=20000, entity="State Medicaid")
    assert any(i["kind"] == "amount" for i in contradictions.detect([a, b], use_llm=False))
    assert not [i for i in contradictions.detect([a, c], use_llm=False) if i["kind"] == "amount"]


def test_conflicting_liability_limits_detected_but_other_layers_ignored():
    a = fact("c1", "coverage", "Limits", "Bodily injury liability $100,000 per person")
    b = fact("c2", "coverage", "Limits", "Liability limits of $250,000 per person")
    um = fact("c3", "coverage", "UM", "Client UM/UIM $25,000 per person")
    assert any(i["kind"] == "coverage" for i in contradictions.detect([a, b], use_llm=False))
    assert not [i for i in contradictions.detect([a, um], use_llm=False) if i["kind"] == "coverage"]


def test_paraphrased_restatements_grouped_not_multiplied():
    fs = [fact("r1", "risk", "Three inconsistent accounts of accident mechanism"),
          fact("r2", "risk", "Three conflicting accounts of the collision exist"),
          fact("r3", "risk", "Client gave inconsistent accounts of the crash")]
    flagged = [i for i in contradictions.detect(fs, use_llm=False) if i["kind"] == "flagged"]
    assert len(flagged) == 1 and len(flagged[0]["related_fact_ids"]) == 3


# ------------------------------------------------------------------------- gaps

BUNDLE = {"contacts": [
    {"id": "p1", "name": "Alpha Orthopedics", "type": "Company", "relationship": "Treating provider, orthopedics", "company": None},
    {"id": "p2", "name": "Beta Imaging Center", "type": "Company", "relationship": "Treating provider, imaging", "company": None}]}


def test_referenced_provider_without_records_is_a_gap():
    fs = [fact("g1", "treatment", "Seen at Alpha Orthopedics for knee pain"), fact("g2", "treatment", "Alpha Orthopedics follow-up visit")]
    issues, chain = gaps.detect(fs, [], BUNDLE)
    g = [i for i in issues if i["kind"] == "records" and "Alpha" in i["title"]]
    assert g and g[0]["explanation"].startswith(gaps.FRAMING)
    assert any(s["name"] == "Alpha Orthopedics" for s in chain)


def test_no_gap_when_records_exist():
    fs = [fact("g1", "treatment", "Seen at Alpha Orthopedics for knee pain"), fact("g2", "treatment", "Alpha Orthopedics follow-up visit")]
    docs = [{"id": "d1", "name": "alpha-orthopedics-records.pdf", "doc_type": "medical_record", "received_at": "2024-04-01"}]
    issues, _ = gaps.detect(fs, docs, BUNDLE)
    assert not [i for i in issues if i["kind"] == "records" and "Alpha" in i["title"]]


def test_recommended_procedure_without_completion_is_dependency_and_resolved_when_performed():
    rec = fact("p1", "treatment", "Right knee arthroscopy recommended by Dr. Smith")
    issues, chain = gaps.detect([rec], [], {"contacts": []})
    assert any(i["kind"] == "procedure" and i["issue_type"] == "dependency" for i in issues)
    assert chain[-1].get("pending")
    done = fact("p2", "treatment", "Right knee arthroscopy performed; operative report", known="2024-06-01")
    issues2, _ = gaps.detect([rec, done], [], {"contacts": []})
    assert not [i for i in issues2 if i["kind"] == "procedure"]


def _sources(facts):
    with db.tx() as c:
        for f in facts:
            c.execute("INSERT OR REPLACE INTO sources(source_type,source_id,title,date,text,meta_json,sha256) VALUES(?,?,?,?,?,?,?)",
                      (f["source_type"], f["source_id"], f["text"], f.get("known_at"), f["quote"], "{}", "x"))


def test_uncertain_findings_are_needs_review():
    old = fact("s1", "treatment", "Treated for back pain", date="2020-01-01")
    _sources([DOI, old])
    issues = service.verify_issues(contradictions.detect([DOI, old], use_llm=False), [DOI, old])
    seq = [i for i in issues if i["kind"] == "sequence"]
    assert seq and seq[0]["verify_status"] == "needs_review"


def test_issue_citing_unsupported_fact_is_hidden():
    a = fact("l1", "lien", "lien", "lien of $1,000", amount=1000, entity="X Lien Co")
    b = fact("l2", "lien", "lien", "lien of $2,000", amount=2000, entity="X Lien Co")
    _sources([a, b])
    issues = contradictions.detect([a, b], use_llm=False)
    assert service.verify_issues(issues, [a, b])  # visible with both facts
    assert service.verify_issues(issues, [a]) == []  # l2 is not a visible fact any more


# ------------------------------------------------------------------- injury map

def test_regions_and_sides_only_when_stated():
    assert ("shoulder", "left") in regions_in("Left shoulder labral tear")
    assert regions_in("Patient reports pain") == []
    m = injury_map([fact("i1", "injury", "Patient reports general pain"), fact("i2", "injury", "Bilateral knee meniscus tear")], [])
    assert [r["key"] for r in m["regions"]] == ["knee"] and m["regions"][0]["sides"] == ["bilateral"]
    assert len(m["unmapped"]) == 1


# ------------------------------------------------------------------------- graph

def test_graph_nodes_from_facts_edges_reference_nodes_and_keep_sources():
    fs = [DOI, fact("i2", "injury", "Left knee meniscus tear", st="document", sid="d1"),
          fact("t1", "treatment", "Alpha Orthopedics treated left knee")]
    issues = service.verify_issues(contradictions.detect(fs, use_llm=False), fs)
    inj = injury_map(fs, issues)
    props = propositions(fs, issues, inj, {})
    g = graph.build(fs, props, issues, inj, {"contacts": BUNDLE["contacts"] + [{"id": "c0", "name": "Pat Client", "is_client": True}]},
                    [], set(), {})
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    fact_nodes = [n for n in g["nodes"] if n["type"] == "fact"]
    assert fact_nodes and all(n["ref"]["source_id"] for n in fact_nodes)
    assert {n["ref"]["fact_id"] for n in fact_nodes} <= {f["fact_id"] for f in fs}
    assert any(e["relationship"] == "TREATED_BY" for e in g["edges"])


# --------------------------------------------------------------- evidence quality

def test_support_state_deterministic_and_rules():
    fs = [fact("a", "injury", "x", st="note"), fact("b", "injury", "y", st="document"), fact("c", "injury", "z", st="communication")]
    s1 = support_state(fs, 0, 0)
    assert s1 == support_state(fs, 0, 0) and s1[0] == "well_corroborated"
    assert support_state(fs, 1, 0)[0] == "conflicting"  # contradictions reduce the state
    assert support_state(fs[:1], 0, 0)[0] == "limited"
    assert support_state(fs[:2], 0, 0)[0] == "supported"  # more verified corroboration improves it
    comp = s1[1]
    assert not any(k for k in comp if "prob" in k or "percent" in k or "score" in k)


# ---------------------------------------------------------------------- security

def test_xray_only_on_attorney_routes():
    from app.main import app

    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert any(p.startswith("/api/attorney/xray") for p in paths)
    assert not any("xray" in p for p in paths if p.startswith("/api/provider"))
    from fastapi.testclient import TestClient
    r = TestClient(app).get("/api/provider/anytoken/xray")
    assert r.status_code == 404 and "issues" not in r.text
    import inspect
    from app import sharing
    assert "xray" not in inspect.getsource(sharing)


# -------------------------------------------------------------------------- cache

def _seed(facts):
    with db.tx() as c:
        c.execute("DELETE FROM facts")
        for f in facts:
            c.execute("INSERT INTO facts(fact_id,type,text,date,amount,entity,source_type,source_id,page,quote,verify_status,extractor) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (f["fact_id"], f["type"], f["text"], f["date"], f["amount"], f["entity"],
                                                         f["source_type"], f["source_id"], f["page"], f["quote"], f["verify_status"], f["extractor"]))
    _sources(facts)
    db.set_setting("bundle", BUNDLE)


def test_unchanged_hash_reuses_cache_changed_hash_recomputes():
    service.init()
    _seed([DOI, fact("t1", "treatment", "Right knee arthroscopy recommended")])
    d1 = {"content_hash": "h1", "attention": {}, "kpis": {}}
    x1 = service.build(d1)
    x1b = service.build(d1)
    assert x1b["generated_at"] == x1["generated_at"]  # cached, not recomputed
    _seed([DOI, fact("t1", "treatment", "Right knee arthroscopy recommended"),
           fact("t2", "treatment", "Right knee arthroscopy performed, operative report", known="2024-07-01")])
    x2 = service.build({"content_hash": "h2", "attention": {}, "kpis": {}})
    assert x2["content_hash"] == "h2"
    proc = [i for i in x1["issues"] if i["kind"] == "procedure"]
    assert proc and proc[0]["id"] in x2["impact"]["resolved"]  # lifecycle: resolved by the new evidence
    row = db.one("SELECT resolved_at FROM case_issues WHERE id=?", (proc[0]["id"],))
    assert row["resolved_at"]


def test_actions_store_drafts_without_sending():
    service.init()
    _seed([DOI, fact("t1", "treatment", "Right knee arthroscopy recommended")])
    x = service.build({"content_hash": "h3", "attention": {}, "kpis": {}})
    iid = x["issues"][0]["id"]
    a = service.add_action(iid, "draft_records_request")
    assert a["status"] == "draft" and "Records request" in a["content"]
    service.add_action(iid, "snooze")
    issues = json.loads(json.dumps(x["issues"]))
    service.attach_reviews(issues)
    assert next(i for i in issues if i["id"] == iid)["review"]["status"] == "snoozed"
    with pytest.raises(ValueError):
        service.add_action(iid, "send_email")
