"""Database engine: connection, schema, and bootstrap.

This is the ONLY place the schema is defined and the connection is opened.
Query logic lives in the `repository` layer, which receives a connection from
here. Nothing outside `core` + `repository` touches SQLite directly.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id            INTEGER PRIMARY KEY,
    app           TEXT NOT NULL,
    title         TEXT NOT NULL,
    identity      TEXT NOT NULL UNIQUE,
    first_seen    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    version_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS versions (
    id          INTEGER PRIMARY KEY,
    thread_id   INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    captured_at REAL NOT NULL,
    hour_bucket INTEGER NOT NULL,
    fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_thread   ON versions(thread_id);
CREATE INDEX IF NOT EXISTS idx_versions_captured ON versions(captured_at);
CREATE INDEX IF NOT EXISTS idx_versions_hour     ON versions(hour_bucket);
CREATE TABLE IF NOT EXISTS embeddings (
    version_id INTEGER PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE,
    dim        INTEGER NOT NULL,
    vec        BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS action_items (
    id                  INTEGER PRIMARY KEY,
    title               TEXT NOT NULL,
    detail              TEXT,
    source_app          TEXT,
    status              TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    resolution_evidence TEXT,
    created_at          REAL NOT NULL,
    resolved_at         REAL,
    fingerprint         TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_items_status ON action_items(status);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_WS = re.compile(r"\s+")


def get_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect() -> sqlite3.Connection:
    """Open + initialise the default database (`config.settings.DB_PATH`)."""
    from ..config import settings
    settings.ensure_base()
    conn = get_conn(settings.DB_PATH)
    init_db(conn)
    return conn


def normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip()).lower()


def fingerprint(*parts: str) -> str:
    h = hashlib.sha256()
    for i, p in enumerate(parts):
        if i:
            h.update(b"\x00")
        h.update(normalize(p).encode("utf-8", "replace"))
    return h.hexdigest()
