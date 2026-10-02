"""Password gate for hosting, and a signing key that survives restarts."""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import auth, signing
from app.main import app


def test_gate_off_without_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "")
    c = TestClient(app)
    assert c.get("/api/health").json()["gate"] is False
    assert c.get("/api/status").status_code == 200


def test_gate_protects_attorney_routes_but_not_provider_links(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret-pass")
    c = TestClient(app)
    for path in ("/api/status", "/api/digest", "/api/share/links", "/api/attorney/xray", "/api/usage"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/sync").status_code == 401
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    tok = c.post("/api/login", json={"password": "s3cret-pass"}).json()["token"]
    assert c.get("/api/status", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    assert c.get(f"/api/status?t={tok}").status_code == 200          # links opened in a new tab
    assert c.get("/api/provider/no-such-token").status_code == 404   # public route: reaches the app, not the gate
    assert c.get("/.well-known/firm-key").status_code == 200
    assert c.get("/api/health").status_code == 200


def test_tokens_expire_and_cannot_be_forged(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret-pass")
    tok = auth.issue()
    assert auth.valid(tok)
    exp, sig = tok.split(".")
    assert not auth.valid(f"{int(exp) + 999}.{sig}")                 # extending expiry breaks the signature
    assert not auth.valid(f"1.{sig}")                                # expired
    monkeypatch.setenv("APP_PASSWORD", "another-pass")
    assert not auth.valid(tok)                                       # password change logs everyone out


def test_signing_key_from_secret_is_stable(monkeypatch):
    pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()).decode()
    monkeypatch.setenv("FIRM_SIGNING_KEY_PEM", pem.replace("\n", "\\n"))  # as pasted into a host's secret field
    monkeypatch.setattr(signing, "_key", None)
    k1 = signing.public_key_b64()
    monkeypatch.setattr(signing, "_key", None)                        # "restart"
    assert signing.public_key_b64() == k1
    s = signing.sign_claim("Current stage: Litigation.", "X", "ab" * 32, "2030-01-01T00:00:00+00:00")
    assert signing.verify(s["payload"], s["signature"], k1)
    monkeypatch.setattr(signing, "_key", None)
