"""MemoryRepository — all reads/writes for threads, versions and embeddings.

Receives an open connection (from `core.database`); nothing else touches SQL.
"""

from __future__ import annotations

import array
import math
import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..core.database import fingerprint, normalize


class MemoryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- writes ----

    def record_capture(self, app: str, title: str, content: str,
                       ts: Optional[float] = None) -> Dict[str, Any]:
        """Upsert a thread and insert a version unless it duplicates the latest.

        Returns {"stored": bool, "thread_id": int, "version_id": Optional[int]}.
        """
        ts = time.time() if ts is None else ts
        identity = "{}{}".format(app or "?", title or "")
        fp = fingerprint(identity, content)
        hour_bucket = int(ts // 3600)
        c = self.conn

        row = c.execute("SELECT id FROM threads WHERE identity = ?", (identity,)).fetchone()
        if row is None:
            cur = c.execute(
                "INSERT INTO threads (app, title, identity, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?)",
                (app or "?", title or "", identity, ts, ts),
            )
            thread_id = cur.lastrowid
        else:
            thread_id = row["id"]
            c.execute("UPDATE threads SET last_seen = ? WHERE id = ?", (ts, thread_id))

        last = c.execute(
            "SELECT fingerprint FROM versions WHERE thread_id = ? "
            "ORDER BY captured_at DESC LIMIT 1", (thread_id,),
        ).fetchone()
        if last is not None and last["fingerprint"] == fp:
            c.commit()
            return {"stored": False, "thread_id": thread_id, "version_id": None}

        cur = c.execute(
            "INSERT INTO versions (thread_id, content, captured_at, hour_bucket, fingerprint) "
            "VALUES (?, ?, ?, ?, ?)",
            (thread_id, content, ts, hour_bucket, fp),
        )
        c.execute(
            "UPDATE threads SET version_count = version_count + 1, last_seen = ? WHERE id = ?",
            (ts, thread_id),
        )
        c.commit()
        return {"stored": True, "thread_id": thread_id, "version_id": cur.lastrowid}

    def store_embedding(self, version_id: int, vec: List[float]) -> None:
        blob = array.array("f", vec).tobytes()
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings (version_id, dim, vec) VALUES (?, ?, ?)",
            (version_id, len(vec), sqlite3.Binary(blob)),
        )
        self.conn.commit()

    # ---- reads ----

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword search over content + title, newest first."""
        like = "%" + normalize(query).replace(" ", "%") + "%"
        rows = self.conn.execute(
            "SELECT v.id, v.content, v.captured_at, t.app, t.title "
            "FROM versions v JOIN threads t ON t.id = v.thread_id "
            "WHERE lower(v.content) LIKE ? OR lower(t.title) LIKE ? "
            "ORDER BY v.captured_at DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 20, minutes: Optional[int] = None) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where = ""
        if minutes is not None:
            where = "WHERE v.captured_at >= ? "
            params.append(time.time() - minutes * 60)
        params.append(limit)
        rows = self.conn.execute(
            "SELECT v.id, v.content, v.captured_at, t.app, t.title "
            "FROM versions v JOIN threads t ON t.id = v.thread_id "
            + where + "ORDER BY v.captured_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def list_threads(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT t.id, t.app, t.title, t.last_seen, t.version_count, "
            "(SELECT content FROM versions v WHERE v.thread_id = t.id "
            " ORDER BY captured_at DESC LIMIT 1) AS preview "
            "FROM threads t ORDER BY t.last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def thread_context(self, thread_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT content, captured_at FROM versions WHERE thread_id = ? "
            "ORDER BY captured_at DESC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        c = self.conn
        return {
            "threads": c.execute("SELECT COUNT(*) n FROM threads").fetchone()["n"],
            "versions": c.execute("SELECT COUNT(*) n FROM versions").fetchone()["n"],
            "embeddings": c.execute("SELECT COUNT(*) n FROM embeddings").fetchone()["n"],
            "last_capture": c.execute("SELECT MAX(captured_at) m FROM versions").fetchone()["m"],
        }

    def semantic_search(self, query_vec: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        """Brute-force cosine over stored vectors (fine for a personal-scale DB)."""
        q = array.array("f", query_vec)
        qnorm = math.sqrt(sum(x * x for x in q)) or 1.0
        scored = []
        for row in self.conn.execute(
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
