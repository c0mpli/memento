"""OpenLoopsService — the part that DOES what Minimi does.

On each run it (1) finds new open loops and (2) auto-closes resolved ones, using
the configured agent (your claude/codex CLI or an API key) over recent memory.
Orchestration only: prompts come from `config.prompts`, all SQL from `repository`.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from ..agents import create_agent, parse_json_object
from ..config import prompts
from ..repository import ActionItemRepository, MemoryRepository
from .notifications import notify


class OpenLoopsService:
    def __init__(self, conn: sqlite3.Connection, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.memory = MemoryRepository(conn)
        self.items = ActionItemRepository(conn)
        self.agent = create_agent(cfg.get("agent", {}))

    def run_once(self, window_minutes: Optional[int] = None) -> Dict[str, int]:
        """Returns {"new": int, "resolved": int}."""
        empty = {"new": 0, "resolved": 0}
        if self.agent is None:
            return empty
        ac = self.cfg.get("agent", {})
        if window_minutes is None:
            window_minutes = int(ac.get("window_minutes", 90))

        activity = self.memory.recent(limit=150, minutes=window_minutes)
        if not activity:
            return empty
        open_now = self.items.open_items(limit=100)

        prompt = prompts.build_open_loops_prompt(open_now, activity)
        try:
            result = parse_json_object(self.agent.complete(prompt))
        except Exception:
            return empty

        new = 0
        for it in result.get("new_loops") or []:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            if title and self.items.add(title, str(it.get("detail") or "").strip(),
                                        str(it.get("source_app") or "").strip()):
                new += 1

        resolved = 0
        open_ids = {i["id"] for i in open_now}
        for it in result.get("resolved") or []:
            if not isinstance(it, dict):
                continue
            try:
                iid = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            if iid in open_ids and self.items.resolve(iid, str(it.get("evidence") or "").strip()):
                resolved += 1

        if new or resolved:
            notify("Memento: +{} open loop(s), {} auto-closed".format(new, resolved),
                   "Ask your assistant: what are my open loops?")
        return {"new": new, "resolved": resolved}
