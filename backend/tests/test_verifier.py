import json

from app import db
from app.agents.verifier import run_verifier
from app.documents import locate_snippet


def _seed():
    with db.tx() as c:
        c.execute("DELETE FROM sources")
        c.execute("DELETE FROM facts")
        c.execute("DELETE FROM doc_pages")
        c.execute("INSERT INTO sources(source_type,source_id,title,date,text,meta_json,sha256) VALUES(?,?,?,?,?,?,?)",
                  ("note", "n1", "Coverage", "2026-09-09", "Defendant liability $100,000 per person / $300,000 per occurrence.", "{}", "x"))
        words = [{"t": "Impression:", "b": [10, 10, 60, 20]}, {"t": "Noevidenceofacutedisplacedfracture", "b": [10, 22, 200, 32]}]
        c.execute("INSERT INTO doc_pages(doc_id,page,text,words_json,method,width,height) VALUES(?,?,?,?,?,?,?)",
                  ("d1", 1, "Impression:\nNoevidenceofacutedisplacedfracture", json.dumps(words), "ocr", 612, 792))
        rows = [
            ("f1", "coverage", "Defendant carries $100,000 per person.", "note", "n1", None, "Defendant liability $100,000 per person", "llm"),
            ("f2", "coverage", "Defendant carries $1,000,000.", "note", "n1", None, "Defendant liability $1,000,000 umbrella policy", "llm"),
            ("f3", "injury", "No acute fracture.", "document", "d1", 1, "No evidence of acute displaced fracture", "llm"),
            ("f4", "coverage", "Limit $100,000.", "note", "n1", None, "liability $100,000 per person / $300,000", "structured"),
        ]
        for r in rows:
            c.execute("INSERT INTO facts(fact_id,type,text,source_type,source_id,page,quote,extractor,verify_status) "
                      "VALUES(?,?,?,?,?,?,?,?,'pending')", r)


def test_quote_must_be_in_source():
    _seed()
    run_verifier()
    st = {r["fact_id"]: r for r in db.query("SELECT * FROM facts")}
    assert st["f1"]["verify_status"] == "quote_ok"     # quote found; semantic LLM check skipped (no key in tests)
    assert st["f2"]["verify_status"] == "unsupported"  # an invented amount is never shown
    assert st["f4"]["verify_status"] == "supported"    # rendered straight from the Clio record


def test_ocr_spacing_does_not_break_matching_and_boxes_returned():
    _seed()
    run_verifier()
    f3 = db.one("SELECT * FROM facts WHERE fact_id='f3'")
    assert f3["verify_status"] == "quote_ok" and f3["page"] == 1
    assert json.loads(f3["bbox_json"]) == [[10, 22, 200, 32]]


def test_locate_fuzzy_ocr_noise():
    words = [{"t": "F1LED: NEW YORK COUNTY CLERK", "b": [0, 0, 100, 10]},
             {"t": "Tendernesspresent.Decreasedrangeof motion", "b": [0, 20, 200, 30]}]
    res = locate_snippet(words, "Tenderness present. Decreased range of motion")
    assert res["match"] == "exact" and res["bboxes"] == [[0, 20, 200, 30]]
    res = locate_snippet(words, "Tenderness presant. Decreased range of motion")
    assert res["match"] == "fuzzy" and res["bboxes"]
    assert locate_snippet(words, "completely unrelated sentence about invoices")["match"] == "none"
