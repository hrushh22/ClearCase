import json

from app.signing import canonical, public_key_b64, sign_claim, verify


def test_sign_and_verify_roundtrip():
    s = sign_claim("Current stage: Litigation.", "00001-Sapini", "ab" * 32, "2026-11-01T00:00:00+00:00")
    assert set(s["package"]) == {"claim", "case_ref", "issued_at", "expires_at", "source_hash"}
    assert s["payload"] == canonical(s["package"])
    assert verify(s["payload"], s["signature"], public_key_b64())


def test_tampered_claim_fails():
    s = sign_claim("Your bill on file: $4,850.00.", "00001-Sapini", "cd" * 32, "2026-11-01T00:00:00+00:00")
    pkg = json.loads(s["payload"])
    pkg["claim"] = "Your bill on file: $48,500.00."
    assert not verify(canonical(pkg), s["signature"])


def test_canonical_is_key_order_independent():
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1}) == '{"a":2,"b":1}'
