"""The only door to Clio. Read-only by construction.

`ClioReadClient` exposes `get()`, `get_all()` and `download()` and nothing else.
Any non-GET request is refused twice over: by `_send()` and by an httpx request
hook on the underlying transport, so even a future code path that reaches into
`self._http` cannot write to Clio. OAuth token exchange lives in clio_auth.py
and never touches case data.
"""
from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from .config import clio_base_url


class ClioWriteAttempt(RuntimeError):
    """Raised when anything tries to send a non-GET request to Clio."""


class ClioError(RuntimeError):
    pass


def _refuse_writes(request: httpx.Request) -> None:
    if request.method.upper() != "GET":
        raise ClioWriteAttempt(f"Blocked {request.method} {request.url}: ClearCase only reads from Clio.")


class ClioReadClient:
    ALLOWED_METHODS = frozenset({"GET"})

    def __init__(self, access_token: str, base_url: str | None = None, on_unauthorized=None,
                 transport: httpx.BaseTransport | None = None):
        self.base = (base_url or clio_base_url()).rstrip("/") + "/api/v4"
        self._token = access_token
        self._on_unauthorized = on_unauthorized
        self.request_count = 0
        self._http = httpx.Client(timeout=60, follow_redirects=True, transport=transport,
                                  event_hooks={"request": [_refuse_writes]})

    def close(self) -> None:
        self._http.close()

    # -- the single choke point ------------------------------------------------
    def _send(self, method: str, url: str, params: dict | None = None, auth: bool = True) -> httpx.Response:
        if method.upper() not in self.ALLOWED_METHODS:
            raise ClioWriteAttempt(f"Blocked {method} {url}: ClearCase only reads from Clio.")
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
        for attempt in range(6):
            self.request_count += 1
            resp = self._http.request("GET", url, params=params, headers=headers)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(wait, 60))
                continue
            if resp.status_code == 401 and auth and self._on_unauthorized and attempt == 0:
                new_token = self._on_unauthorized()
                if new_token:
                    self._token = new_token
                    headers = {"Authorization": f"Bearer {self._token}"}
                    continue
            return resp
        return resp

    # -- public read API ---------------------------------------------------------
    def get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        resp = self._send("GET", url, params=params)
        if resp.status_code >= 400:
            raise ClioError(f"GET {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def iter_pages(self, path: str, params: dict | None = None) -> Iterator[dict[str, Any]]:
        params = {"limit": 200, **(params or {})}
        data = self.get(path, params)
        while True:
            yield from data.get("data", []) or []
            nxt = ((data.get("meta") or {}).get("paging") or {}).get("next")
            if not nxt:
                break
            data = self.get(nxt)

    def get_all(self, path: str, params: dict | None = None, fields_options: list[str] | None = None) -> list[dict]:
        """List endpoint with pagination. Tries richer `fields` first, falls back on 400."""
        last_err: Exception | None = None
        for fields in fields_options or [None]:
            p = dict(params or {})
            if fields:
                p["fields"] = fields
            try:
                return list(self.iter_pages(path, p))
            except ClioError as e:
                last_err = e
                if "-> 400" not in str(e) and "-> 422" not in str(e):
                    raise
        raise last_err or ClioError(f"GET {path} failed")

    def download(self, document_id: str | int) -> bytes:
        resp = self._send("GET", f"{self.base}/documents/{document_id}/download")
        if resp.status_code >= 400:
            raise ClioError(f"download {document_id} -> {resp.status_code}")
        return resp.content
