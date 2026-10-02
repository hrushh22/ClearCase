"""Clio OAuth 2.0 (authorization code). Only obtains tokens; never touches case data.

Tokens are stored in our own DB (settings table), falling back to .env values.
"""
from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import httpx

from . import db
from .config import ConfigError, clio_base_url, env, require


def authorize_url() -> str:
    state = secrets.token_urlsafe(16)
    db.set_setting("clio_oauth_state", state)
    q = urlencode({
        "response_type": "code",
        "client_id": require("CLIO_CLIENT_ID", "the Clio OAuth login"),
        "redirect_uri": env("CLIO_REDIRECT_URI", "http://localhost:8000/auth/clio/callback"),
        "state": state,
    })
    return f"{clio_base_url()}/oauth/authorize?{q}"


def _store(tokens: dict) -> str:
    db.set_setting("clio_tokens", {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token") or (db.get_setting("clio_tokens", {}) or {}).get("refresh_token"),
        "expires_at": time.time() + float(tokens.get("expires_in", 3600)),
    })
    return tokens["access_token"]


def exchange_code(code: str, state: str) -> str:
    if state != db.get_setting("clio_oauth_state"):
        raise ConfigError("OAuth state mismatch; start again at /auth/clio/login.")
    resp = httpx.post(f"{clio_base_url()}/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "client_id": require("CLIO_CLIENT_ID", "the Clio OAuth login"),
        "client_secret": require("CLIO_CLIENT_SECRET", "the Clio OAuth login"),
        "redirect_uri": env("CLIO_REDIRECT_URI", "http://localhost:8000/auth/clio/callback"),
    }, timeout=30)
    resp.raise_for_status()
    return _store(resp.json())


def refresh() -> str | None:
    stored = db.get_setting("clio_tokens", {}) or {}
    rt = stored.get("refresh_token") or env("CLIO_REFRESH_TOKEN")
    if not (rt and env("CLIO_CLIENT_ID") and env("CLIO_CLIENT_SECRET")):
        return None
    resp = httpx.post(f"{clio_base_url()}/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": rt,
        "client_id": env("CLIO_CLIENT_ID"), "client_secret": env("CLIO_CLIENT_SECRET"),
    }, timeout=30)
    if resp.status_code >= 400:
        return None
    return _store(resp.json())


def access_token() -> str:
    stored = db.get_setting("clio_tokens", {}) or {}
    if stored.get("access_token"):
        if stored.get("expires_at", 0) < time.time() + 60:
            return refresh() or stored["access_token"]
        return stored["access_token"]
    tok = env("CLIO_ACCESS_TOKEN")
    if tok:
        return tok
    raise ConfigError(
        "No Clio access token. Either paste CLIO_ACCESS_TOKEN in .env, or fill CLIO_CLIENT_ID and "
        "CLIO_CLIENT_SECRET and open http://localhost:8000/auth/clio/login once.")


def status() -> dict:
    stored = db.get_setting("clio_tokens", {}) or {}
    return {"connected": bool(stored.get("access_token") or env("CLIO_ACCESS_TOKEN")),
            "oauth_configured": bool(env("CLIO_CLIENT_ID") and env("CLIO_CLIENT_SECRET"))}
