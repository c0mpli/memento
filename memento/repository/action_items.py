"""ActionItemRepository — reads/writes for open loops (action items)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..core.database import fingerprint
from ..types import ItemStatus


class ActionItemRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, title: str, detail: str = "", source_app: str = "",
            ts: Optional[float] = None) -> bool:
        """Insert a new open loop. Returns False if it's a duplicate."""
        ts = time.time() if ts is None else ts
        fp = fingerprint("action", title)
        try:
            self.conn.execute(
                "INSERT INTO action_items (title, detail, source_app, status, created_at, fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title, detail, source_app, ItemStatus.OPEN.value, ts, fp),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def resolve(self, item_id: int, evidence: str = "",
                ts: Optional[float] = None) -> bool:
        """Mark an open loop resolved. Returns True if it was open and got closed."""
        ts = time.time() if ts is None else ts
        cur = self.conn.execute(
            "UPDATE action_items SET status=?, resolved_at=?, resolution_evidence=? "
            "WHERE id=? AND status=?",
            (ItemStatus.RESOLVED.value, ts, evidence, item_id, ItemStatus.OPEN.value),
        )
        self.conn.commit()
        return bool(cur.rowcount and cur.rowcount > 0)

    def open_items(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, title, detail, source_app, created_at FROM action_items "
            "WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (ItemStatus.OPEN.value, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def resolved_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, title, resolution_evidence, resolved_at FROM action_items "
            "WHERE status=? ORDER BY resolved_at DESC LIMIT ?",
            (ItemStatus.RESOLVED.value, limit),
        ).fetchall()
        return [dict(r) for r in rows]
