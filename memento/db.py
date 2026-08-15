"""The local memory store.

Data model (a clean-room take on the thread/version idea):

    threads   one identity = one app + window title. The thing you were in.
    versions  point-in-time snapshots of a thread's content, deduped by
              fingerprint so re-reading the same screen doesn't pile up rows.
    embeddings optional per-version vectors for semantic search.

Everything is local SQLite. No network, no cloud.
"""

from __future__ import annotations

import array
import hashlib
import math
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip()).lower()


def fingerprint(identity: str, content: str) -> str:
    h = hashlib.sha256()
    h.update(identity.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(normalize(content).encode("utf-8", "replace"))
    return h.hexdigest()


def record_capture(
    conn: sqlite3.Connection,
    app: str,
    title: str,
    content: str,
    ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Upsert a thread and insert a version unless it duplicates the latest one.

    Returns {"stored": bool, "thread_id": int, "version_id": Optional[int]}.
    """
    ts = time.time() if ts is None else ts
    identity = "{}{}".format(app or "?", title or "")
    fp = fingerprint(identity, content)
    hour_bucket = int(ts // 3600)

    row = conn.execute("SELECT id FROM threads WHERE identity = ?", (identity,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO threads (app, title, identity, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (app or "?", title or "", identity, ts, ts),
        )
        thread_id = cur.lastrowid
    else:
        thread_id = row["id"]
        conn.execute("UPDATE threads SET last_seen = ? WHERE id = ?", (ts, thread_id))

    last = conn.execute(
        "SELECT fingerprint FROM versions WHERE thread_id = ? "
        "ORDER BY captured_at DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    if last is not None and last["fingerprint"] == fp:
        conn.commit()  # nothing new on screen; just the bumped last_seen
        return {"stored": False, "thread_id": thread_id, "version_id": None}

    cur = conn.execute(
        "INSERT INTO versions (thread_id, content, captured_at, hour_bucket, fingerprint) "
        "VALUES (?, ?, ?, ?, ?)",
        (thread_id, content, ts, hour_bucket, fp),
    )
    conn.execute(
        "UPDATE threads SET version_count = version_count + 1, last_seen = ? WHERE id = ?",
        (ts, thread_id),
    )
    conn.commit()
    return {"stored": True, "thread_id": thread_id, "version_id": cur.lastrowid}


def search(conn: sqlite3.Connection, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Keyword search over content + title, newest first. Zero-cost, no keys."""
    like = "%" + normalize(query).replace(" ", "%") + "%"
    rows = conn.execute(
        "SELECT v.id, v.content, v.captured_at, t.app, t.title "
        "FROM versions v JOIN threads t ON t.id = v.thread_id "
        "WHERE lower(v.content) LIKE ? OR lower(t.title) LIKE ? "
        "ORDER BY v.captured_at DESC LIMIT ?",
        (like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def recent(conn: sqlite3.Connection, limit: int = 20,
           minutes: Optional[int] = None) -> List[Dict[str, Any]]:
    params: List[Any] = []
    where = ""
    if minutes is not None:
        where = "WHERE v.captured_at >= ? "
        params.append(time.time() - minutes * 60)
    params.append(limit)
    rows = conn.execute(
        "SELECT v.id, v.content, v.captured_at, t.app, t.title "
        "FROM versions v JOIN threads t ON t.id = v.thread_id "
        + where +
        "ORDER BY v.captured_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def list_threads(conn: sqlite3.Connection, limit: int = 20) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT t.id, t.app, t.title, t.last_seen, t.version_count, "
        "(SELECT content FROM versions v WHERE v.thread_id = t.id "
        " ORDER BY captured_at DESC LIMIT 1) AS preview "
        "FROM threads t ORDER BY t.last_seen DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def thread_context(conn: sqlite3.Connection, thread_id: int,
                   limit: int = 20) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT content, captured_at FROM versions WHERE thread_id = ? "
        "ORDER BY captured_at DESC LIMIT ?",
        (thread_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    t = conn.execute("SELECT COUNT(*) c FROM threads").fetchone()["c"]
    v = conn.execute("SELECT COUNT(*) c FROM versions").fetchone()["c"]
    e = conn.execute("SELECT COUNT(*) c FROM embeddings").fetchone()["c"]
    last = conn.execute("SELECT MAX(captured_at) m FROM versions").fetchone()["m"]
    return {"threads": t, "versions": v, "embeddings": e, "last_capture": last}


# ---- optional semantic search (only used when embeddings are configured) ----

def store_embedding(conn: sqlite3.Connection, version_id: int, vec: List[float]) -> None:
    blob = array.array("f", vec).tobytes()
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (version_id, dim, vec) VALUES (?, ?, ?)",
        (version_id, len(vec), sqlite3.Binary(blob)),
    )
    conn.commit()


def semantic_search(conn: sqlite3.Connection, query_vec: List[float],
                    limit: int = 10) -> List[Dict[str, Any]]:
    """Brute-force cosine over stored vectors. Fine for a personal-scale DB."""
    q = array.array("f", query_vec)
    qnorm = math.sqrt(sum(x * x for x in q)) or 1.0
    scored = []
    for row in conn.execute(
        "SELECT e.version_id, e.vec, v.content, v.captured_at, t.app, t.title "
        "FROM embeddings e JOIN versions v ON v.id = e.version_id "
        "JOIN threads t ON t.id = v.thread_id"
    ):
        vec = array.array("f")
        vec.frombytes(row["vec"])
        if len(vec) != len(q):
            continue
        dot = sum(a * b for a, b in zip(q, vec))
        vnorm = math.sqrt(sum(x * x for x in vec)) or 1.0
        scored.append((dot / (qnorm * vnorm), row))
    scored.sort(key=lambda p: p[0], reverse=True)
    out = []
    for score, row in scored[:limit]:
        d = {k: row[k] for k in ("version_id", "content", "captured_at", "app", "title")}
        d["score"] = round(score, 4)
        out.append(d)
    return out
