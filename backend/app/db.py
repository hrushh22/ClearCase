"""Our own SQLite database (outside Clio). Plain sqlite3, one connection per call."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, clio_id TEXT NOT NULL, payload_json TEXT NOT NULL, fetched_at TEXT NOT NULL,
  UNIQUE(kind, clio_id));
CREATE TABLE IF NOT EXISTS sources(
  source_type TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT, date TEXT, text TEXT NOT NULL,
  meta_json TEXT, sha256 TEXT NOT NULL,
  PRIMARY KEY(source_type, source_id));
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, clio_id TEXT, name TEXT, folder TEXT, doc_type TEXT, sha256 TEXT,
  page_count INTEGER, local_path TEXT, received_at TEXT, scanned_pages INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS doc_pages(
  doc_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL, words_json TEXT NOT NULL,
  method TEXT NOT NULL, width REAL, height REAL,
  PRIMARY KEY(doc_id, page));
CREATE TABLE IF NOT EXISTS facts(
  fact_id TEXT PRIMARY KEY, type TEXT, text TEXT, date TEXT, amount REAL, entity TEXT,
  source_type TEXT, source_id TEXT, page INTEGER, quote TEXT, bbox_json TEXT, confidence REAL,
  verify_status TEXT, verify_reason TEXT, extractor TEXT, source_sha TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS extraction_runs(
  source_type TEXT NOT NULL, source_id TEXT NOT NULL, part TEXT NOT NULL, source_sha TEXT NOT NULL,
  extractor TEXT, created_at TEXT, PRIMARY KEY(source_type, source_id, part));
CREATE TABLE IF NOT EXISTS digests(
  content_hash TEXT PRIMARY KEY, created_at TEXT, record_count INTEGER,
  snapshot_json TEXT, kpis_json TEXT, stage_json TEXT, timeline_json TEXT, top10_json TEXT,
  attention_json TEXT, injuries_json TEXT, contact_json TEXT, waterfall_json TEXT,
  facts_json TEXT, model_log_json TEXT);
CREATE TABLE IF NOT EXISTS views(
  user_id TEXT PRIMARY KEY, last_viewed_digest_hash TEXT, last_viewed_at TEXT,
  previous_digest_hash TEXT, previous_viewed_at TEXT);
CREATE TABLE IF NOT EXISTS share_links(
  token TEXT PRIMARY KEY, provider_name TEXT, created_at TEXT, expires_at TEXT,
  allowed_claims_json TEXT, revoked INTEGER DEFAULT 0, notify_email TEXT);
CREATE TABLE IF NOT EXISTS share_claims(
  id TEXT PRIMARY KEY, share_token TEXT, claim_text TEXT, payload_json TEXT, source_hash TEXT,
  signature TEXT, issued_at TEXT, expires_at TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS access_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, opened_at TEXT, ip_hash TEXT, user_agent TEXT);
CREATE TABLE IF NOT EXISTS change_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, kind TEXT, summary TEXT, source_ref TEXT,
  provider_visible INTEGER DEFAULT 0, digest_hash TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, task TEXT, provider TEXT, model TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, ok INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, response_json TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS facts_src ON facts(source_type, source_id);
"""

_lock = threading.RLock()
_initialized = False


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# columns added after the first release: (table, column, type). Added in place on older databases.
MIGRATIONS = [("share_claims", "category", "TEXT"), ("share_claims", "claim_key", "TEXT"),
              ("share_claims", "superseded", "INTEGER DEFAULT 0"), ("change_events", "share_token", "TEXT")]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, typ in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    # claims created before keys existed: key = the id after the link prefix ("Ab12Cd34_stage" -> "stage")
    for row in conn.execute("SELECT id FROM share_claims WHERE claim_key IS NULL").fetchall():
        key = row[0].split("_", 1)[1] if "_" in row[0] else row[0]
        key = "stage" if key.startswith("stage_") else "waterfall_position" if key == "waterfall" else key
        conn.execute("UPDATE share_claims SET claim_key=? WHERE id=?", (key, row[0]))
    conn.commit()


def connect() -> sqlite3.Connection:
    global _initialized
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    if not _initialized:
        with _lock:
            conn.executescript(SCHEMA)
            _migrate(conn)
            _initialized = True
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        with _lock:
            yield conn
            conn.commit()
    finally:
        conn.close()


def query(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def get_setting(key: str, default: Any = None) -> Any:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value: Any) -> None:
    with tx() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))
