"""Signed selective disclosure: Ed25519 over a canonical claim package.

Package: {claim, case_ref, issued_at, expires_at, source_hash}. `source_hash` is the SHA-256 of the
cited source text, so the firm can later reveal that source and anyone can check it matches.
This is NOT a zero-knowledge proof; it lets a provider verify a claim came from the firm, unaltered,
without seeing the file.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import env, signing_key_path

_key: Ed25519PrivateKey | None = None


def canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def private_key() -> Ed25519PrivateKey:
    global _key
    if _key:
        return _key
    pem = env("FIRM_SIGNING_KEY_PEM")  # hosted: the key lives in a secret so it survives restarts
    if pem:
        # secrets often arrive with literal "\n" sequences instead of line breaks
        _key = serialization.load_pem_private_key(pem.replace("\\n", "\n").encode(), password=None)
        return _key
    path = signing_key_path()
    if path.exists():
        _key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        _key = Ed25519PrivateKey.generate()
        path.write_bytes(_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    return _key


def public_key_b64() -> str:
    raw = private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def sign_claim(claim: str, case_ref: str, source_hash: str, expires_at: str, issued_at: str | None = None) -> dict:
    issued_at = issued_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    package = {"claim": claim, "case_ref": case_ref, "issued_at": issued_at, "expires_at": expires_at, "source_hash": source_hash}
    payload = canonical(package)
    sig = private_key().sign(payload.encode("utf-8"))
    return {"package": package, "payload": payload, "signature": base64.b64encode(sig).decode()}


def verify(payload: str, signature_b64: str, public_key_b64_: str | None = None) -> bool:
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64_ or public_key_b64()))
    try:
        pub.verify(base64.b64decode(signature_b64), payload.encode("utf-8"))
        return True
    except Exception:
        return False
