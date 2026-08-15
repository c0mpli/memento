"""DerivativeRepository — atomic facts distilled from raw activity.

Facts are the high-precision retrieval unit: self-contained statements with a
timestamp, a subject (for supersession), and an optional embedding. Superseded
facts are kept but marked invalid so the latest state wins.
"""

from __future__ import annotations

import array
import math
import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..core.database import fingerprint, normalize
from .memory import _tokens


class DerivativeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, content: str, kind: str = "fact", subject: str = "",
            version_id: Optional[int] = None, thread_id: Optional[int] = None,
            captured_at: Optional[float] = None, updates: bool = False) -> Optional[int]:
        captured_at = time.time() if captured_at is None else captured_at
        subj = normalize(subject)
        if updates and subj:
            # a changed state invalidates earlier facts on the same subject
            self.conn.execute(
                "UPDATE derivatives SET valid=0 WHERE subject=? AND valid=1", (subj,))
        fp = fingerprint("deriv", content)
        try:
            cur = self.conn.execute(
                "INSERT INTO derivatives (version_id, thread_id, kind, content, subject, "
                "captured_at, valid, fingerprint) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (version_id, thread_id, kind, content, subj, captured_at, fp),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def store_embedding(self, derivative_id: int, vec: List[float]) -> None:
        blob = array.array("f", vec).tobytes()
        self.conn.execute(
            "INSERT OR REPLACE INTO derivative_embeddings (derivative_id, dim, vec) "
            "VALUES (?, ?, ?)", (derivative_id, len(vec), sqlite3.Binary(blob)))
        self.conn.commit()

    # ---- retrieval ----

    def _time_sql(self, tf: Optional[float], tt: Optional[float], params: List[Any]) -> str:
        sql = ""
        if tf is not None:
            sql += " AND captured_at >= ?"
            params.append(tf)
        if tt is not None:
            sql += " AND captured_at <= ?"
            params.append(tt)
        return sql

    def keyword_search(self, query: str, limit: int = 10,
                       time_from: Optional[float] = None,
                       time_to: Optional[float] = None) -> List[Dict[str, Any]]:
        tokens = _tokens(query)
        params: List[Any] = []
        if tokens:
            clause = " OR ".join(["lower(content) LIKE ? OR lower(subject) LIKE ?"] * len(tokens))
            for tok in tokens:
                like = "%" + tok + "%"
                params.extend([like, like])
            where = "valid=1 AND (" + clause + ")"
        else:
            where = "valid=1"
        where += self._time_sql(time_from, time_to, params)
        rows = self.conn.execute(
            "SELECT id, content, subject, captured_at FROM derivatives WHERE "
            + where + " ORDER BY captured_at DESC LIMIT 300", params).fetchall()
        if not tokens:
            return [dict(r) for r in rows[:limit]]
        scored = []
        for r in rows:
            hay = (r["content"] or "").lower() + " " + (r["subject"] or "").lower()
            score = sum(1 for tok in tokens if tok in hay)
            if score:
                scored.append((score, r["captured_at"], r))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [dict(r) for _, _, r in scored[:limit]]

    def semantic_search(self, query_vec: List[float], limit: int = 10,
                        time_from: Optional[float] = None,
                        time_to: Optional[float] = None) -> List[Dict[str, Any]]:
        q = array.array("f", query_vec)
        qn = math.sqrt(sum(x * x for x in q)) or 1.0
        params: List[Any] = []
        where = "valid=1" + self._time_sql(time_from, time_to, params)
        scored = []
        for row in self.conn.execute(
            "SELECT d.id, d.content, d.subject, d.captured_at, e.vec "
            "FROM derivatives d JOIN derivative_embeddings e ON e.derivative_id = d.id "
            "WHERE " + where, params):
            vec = array.array("f")
            vec.frombytes(row["vec"])
            if len(vec) != len(q):
                continue
            dot = sum(a * b for a, b in zip(q, vec))
            vn = math.sqrt(sum(x * x for x in vec)) or 1.0
            scored.append((dot / (qn * vn), row))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, row in scored[:limit]:
            out.append({"id": row["id"], "content": row["content"],
                        "subject": row["subject"], "captured_at": row["captured_at"],
                        "score": round(score, 4)})
        return out

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) n FROM derivatives WHERE valid=1").fetchone()["n"]
