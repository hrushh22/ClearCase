"""Chat: attorney answers cite real items; provider chat sees ONLY that link's approved claims; voice limits."""
import json

import pytest
from fastapi.testclient import TestClient

from app import chat, db, sharing
from app.main import app
from tests.test_live_updates import _digest, _setup


class _Fake:
    """Stands in for the LLM: records the prompt, returns a fixed answer."""
    def __init__(self, answer, citations):
        self.answer, self.citations, self.prompts = answer, citations, []

    def __call__(self, task, prompt, schema, images=None):
        self.prompts.append(prompt)
        return schema(answer=self.answer, citations=self.citations)


def _seed_facts():
    with db.tx() as c:
        c.execute("DELETE FROM facts")
        rows = [("f_lien", "lien", "Medicaid lien of $22,180", "note", "n1", "Medicaid lien of $22,180", "supported"),
                ("f_knee", "injury", "Left knee meniscus tear", "document", "d1", "meniscus tear", "supported"),
                ("f_bad", "lien", "Invented lien of $1,000,000", "note", "n2", "nothing", "unsupported")]
        for r in rows:
            c.execute("INSERT INTO facts(fact_id,type,text,source_type,source_id,quote,verify_status) VALUES(?,?,?,?,?,?,?)", r)


def test_attorney_chat_cites_only_real_items_and_never_sees_hidden_facts(monkeypatch):
    _seed_facts()
    fake = _Fake("The Medicaid lien is $22,180 [1]. Also [99].", ["1", "99"])
    monkeypatch.setattr(chat, "complete_json", fake)
    monkeypatch.setattr(chat, "available_providers", lambda: ["groq"])
    monkeypatch.setattr(chat, "_key_items", lambda: [])
    r = chat.attorney_chat("What is the Medicaid lien?")
    assert [c["fact_id"] for c in r["citations"]] == ["f_lien"]     # [99] does not exist -> dropped
    assert "[99]" not in r["answer"]
    assert "1,000,000" not in fake.prompts[0]                        # unsupported facts are never given to the model
    assert "Medicaid lien of $22,180" in fake.prompts[0].split("QUESTION")[0]


def test_attorney_chat_offline_is_graceful(monkeypatch):
    monkeypatch.setattr(chat, "available_providers", lambda: [])
    r = chat.attorney_chat("anything?")
    assert r["offline"] and r["citations"] == []


def test_provider_chat_prompt_holds_only_this_links_approved_claims(monkeypatch):
    _setup()
    d = _digest()
    tok = sharing.create_link(d, "p1", ["status", "need_t1"])["token"]
    fake = _Fake("The firm needs records batch t1 [2].", ["2"])
    monkeypatch.setattr(chat, "complete_json", fake)
    monkeypatch.setattr(chat, "available_providers", lambda: ["groq"])
    r = chat.provider_chat(tok, "What do you need from us? Also, what is the case worth?")
    prompt = fake.prompts[0].split("CONVERSATION SO FAR")[0]
    assert "Records batch t1" in prompt
    assert "500,000" not in prompt and "Current stage" not in prompt   # strategy and unapproved items never reach the model
    assert r["citations"] and r["citations"][0]["claim_id"].startswith(tok[:8])
    sharing.revoke(tok)
    assert chat.provider_chat(tok, "hello")["error"] == "inactive"
    assert chat.provider_chat("nope", "hello")["error"] == "not_found"


def test_chat_routes_respect_the_password_gate(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw-123")
    c = TestClient(app)
    assert c.post("/api/chat", json={"question": "hi"}).status_code == 401
    assert c.post("/api/chat/transcribe", content=b"x", headers={"Content-Type": "audio/webm"}).status_code == 401
    assert c.post("/api/provider/no-such/chat", json={"question": "hi"}).status_code == 404       # public, but link must exist
    assert c.post("/api/provider/no-such/transcribe", content=b"x", headers={"Content-Type": "audio/webm"}).status_code == 404


def test_transcribe_limits(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    with pytest.raises(ValueError):
        chat.transcribe(b"", "audio/webm")
    with pytest.raises(OverflowError):
        chat.transcribe(b"0" * (chat.MAX_AUDIO_BYTES + 1), "audio/webm")
    monkeypatch.setenv("GROQ_API_KEY", "")
    with pytest.raises(LookupError):
        chat.transcribe(b"abc", "audio/webm")
