"""Attorney password gate for public hosting.

APP_PASSWORD empty  -> no gate (local use, unchanged behaviour).
APP_PASSWORD set    -> every attorney route needs a session token from POST /api/login, sent as
                       `Authorization: Bearer <token>` (or `?t=<token>` for links opened in a new tab).
Always public: provider links (/api/provider/*), the firm's public key, the Clio OAuth callback, health and login.
Tokens are HMAC-signed and expire; the password itself is never stored in the browser.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import env

TTL = 7 * 24 * 3600
PUBLIC_PREFIXES = ("/api/provider/", "/.well-known/", "/auth/clio/callback", "/api/login", "/api/health")


def enabled() -> bool:
    return bool(env("APP_PASSWORD"))


def _secret() -> bytes:
    return hashlib.sha256(("clearcase-session|" + env("APP_PASSWORD")).encode()).digest()


def issue() -> str:
    exp = str(int(time.time()) + TTL)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).digest()
    return f"{exp}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < time.time():
        return False
    good = base64.urlsafe_b64encode(hmac.new(_secret(), exp.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return hmac.compare_digest(good, sig)


def check_password(password: str) -> bool:
    return enabled() and hmac.compare_digest(password.encode(), env("APP_PASSWORD").encode())


def needs_auth(path: str) -> bool:
    if not enabled() or path.startswith(PUBLIC_PREFIXES):
        return False
    return path.startswith("/api/") or path.startswith("/auth/")


async def middleware(request: Request, call_next):
    if request.method != "OPTIONS" and needs_auth(request.url.path):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("t")
        if not valid(token):
            return JSONResponse(status_code=401, content={"error": "auth", "detail": "Password required"})
    return await call_next(request)
