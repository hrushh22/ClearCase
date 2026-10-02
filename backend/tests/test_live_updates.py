"""Shared provider links follow the case: changed items re-signed, new items in approved categories added,
items that no longer apply withdrawn; strategy never appears; polling is not logged as an open."""
import copy
import json

from app import db, sharing
from app.signing import verify

PROVIDER = {"id": "p1", "name": "Alpha Orthopedics", "type": "Company", "relationship": "Treating provider, orthopedics", "company": None}


def _digest(stage="Litigation", needs=("t1",), visits=()):
    ev = {"fact_id": "f1", "source_type": "note", "source_id": "n1", "page": None, "quote": "Suit filed", "date": "2026-01-01"}
    return {
        "content_hash": f"h-{stage}-{'-'.join(needs)}",
        "snapshot": {"matter_id": "m1", "display_number": "00001-Test", "status": "Open"},
        "stage": {"stage": stage, "alive": True, "evidence": [ev], "last_movement": ev},
        "kpis": {"coverage": {"headline": "x", "value": None, "sources": []}, "specials": {"providers": []}},
        "attention": {"waiting": [{"source_type": "task", "source_id": t, "title": f"By medical provider: Alpha Orthopedics - item {t}",
                                   "waiting_on": "Alpha Orthopedics", "detail": f"Records batch {t}", "due": "2026-12-01"} for t in needs],
                      "upcoming": [{"source_type": "calendar", "source_id": v, "title": "Client treatment: Alpha Orthopedics visit",
                                    "kind": "calendar", "due": "2026-12-05"} for v in visits]},
        "facts": [{"fact_id": "s1", "type": "valuation", "text": "Case worth $500,000", "quote": "worth $500,000", "source_type": "note",
                   "source_id": "n2", "page": None, "verify_status": "supported", "date": "2026-01-02"}],
        "waterfall": {"liens": [], "expenses": [], "suggested_gross": 100000},
    }


def _setup():
    db.set_setting("bundle", {"contacts": [PROVIDER]})
    db.set_setting("waterfall", {})
    with db.tx() as c:
        for t in ("share_links", "share_claims", "change_events", "access_log"):
            c.execute(f"DELETE FROM {t}")


def test_link_follows_the_case():
    _setup()
    d1 = _digest()
    link = sharing.create_link(d1, "p1", ["status", "stage", "need_t1"])
    tok = link["token"]
    before = {c["key"]: c for c in sharing.provider_view(tok, "1.2.3.4", "test", poll=True)["claims"]}
    assert set(before) == {"status", "stage", "need_t1"}

    # the case moves: new stage, the old request is done, a new request appears, a visit is booked
    d2 = _digest(stage="Settlement", needs=("t2",), visits=("v1",))
    changes = sharing.refresh_links(d2)[tok]
    assert any(c.startswith("Updated: Current stage: Settlement") for c in changes)
    assert any(c.startswith("No longer applies:") and "t1" in c for c in changes)
    assert any(c.startswith("New:") and "t2" in c for c in changes)          # needs were approved -> new needs flow
    assert not any("visit" in c.lower() for c in changes)                  # treatment was never approved -> no auto-add
    assert not any("500,000" in c for c in changes)                        # strategy never leaks

    view = sharing.provider_view(tok, "1.2.3.4", "test", poll=True)
    keys = {c["key"] for c in view["claims"]}
    assert keys == {"status", "stage", "need_t2", "last_movement"}  # last activity is a status item -> auto-added
    stage = next(c for c in view["claims"] if c["key"] == "stage")
    assert "Settlement" in json.loads(stage["payload"])["claim"]
    assert all(verify(c["payload"], c["signature"], view["public_key"]) for c in view["claims"])
    assert len(view["events"]) == len(changes)
    assert view["updated_at"] >= view["created_at"]

    assert sharing.refresh_links(copy.deepcopy(d2)) == {}  # nothing changed -> nothing re-issued


def test_polling_is_not_counted_as_an_open_and_revoked_links_stop():
    _setup()
    tok = sharing.create_link(_digest(), "p1", ["status"])["token"]
    sharing.provider_view(tok, "1.2.3.4", "test")
    sharing.provider_view(tok, "1.2.3.4", "test", poll=True)
    assert db.one("SELECT COUNT(*) n FROM access_log WHERE token=?", (tok,))["n"] == 1
    sharing.revoke(tok)
    assert sharing.refresh_links(_digest(stage="Settlement")) == {}
    assert sharing.provider_view(tok, "1.2.3.4", "test", poll=True)["error"] == "revoked"
