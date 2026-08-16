"""DerivationService — distill raw activity into atomic facts.

Extraction (an LLM call) is the expensive part, so it can run concurrently; the
SQLite writes stay on one thread. In the product this runs in the background on
newly-committed versions; the eval uses it to index each haystack session.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from ..agents import create_agent, create_named_agent, parse_json_array
from ..config import prompts
from ..repository import DerivativeRepository


class DerivationService:
    def __init__(self, conn: sqlite3.Connection, cfg: Dict[str, Any], agent=None):
        self.cfg = cfg
        self.repo = DerivativeRepository(conn)
        self.agent = agent or self._build_agent(cfg)

    @staticmethod
    def _build_agent(cfg: Dict[str, Any]):
        dc = cfg.get("derivation") or {}
        if dc.get("provider"):
            return create_named_agent(dc["provider"], dc.get("model", ""), dc.get("api_key_env", ""))
        return create_agent(cfg.get("agent", {}))

    def _extract(self, conversation: str) -> List[Dict[str, Any]]:
        if not self.agent or not conversation.strip():
            return []
        try:
            return parse_json_array(self.agent.complete(prompts.build_extraction_prompt(conversation)))
        except Exception:
            return []

    def _session_text(self, turns: List[Dict[str, Any]]) -> str:
        return "\n".join("{}: {}".format(t.get("role", "user"), t.get("content", ""))
                         for t in turns if t.get("content"))

    def _store(self, facts: List[Dict[str, Any]], thread_id: Optional[int],
               captured_at: Optional[float], version_id: Optional[int]) -> List[Tuple[int, str]]:
        added: List[Tuple[int, str]] = []
        for f in facts:
            if not isinstance(f, dict):
                continue
            content = str(f.get("content") or "").strip()
            if not content:
                continue
            did = self.repo.add(
                content, kind=str(f.get("kind", "fact")), subject=str(f.get("subject") or ""),
                version_id=version_id, thread_id=thread_id, captured_at=captured_at,
                updates=bool(f.get("updates")))
            if did:
                added.append((did, content))
        return added

    def session_facts(self, turns: List[Dict[str, Any]]) -> List[str]:
        """Return atomic fact strings for a session (for key augmentation)."""
        return [str(f.get("content") or "").strip()
                for f in self._extract(self._session_text(turns))
                if isinstance(f, dict) and str(f.get("content") or "").strip()]

    def facts_for_sessions(self, sessions: List[List[Dict[str, Any]]],
                           workers: int = 8) -> List[List[str]]:
        """Extract facts for many sessions concurrently; order preserved."""
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(self.session_facts, sessions))

    def ingest_session(self, turns: List[Dict[str, Any]], thread_id: Optional[int] = None,
                       captured_at: Optional[float] = None,
                       version_id: Optional[int] = None) -> List[Tuple[int, str]]:
        return self._store(self._extract(self._session_text(turns)), thread_id, captured_at, version_id)

    def ingest_sessions(self, sessions: List[Dict[str, Any]], workers: int = 8) -> List[Tuple[int, str]]:
        """sessions: list of {turns, captured_at, thread_id}. Extraction runs in
        parallel; facts are stored in the given (chronological) order so that
        `updates` supersedes earlier facts correctly."""
        def extract_one(s: Dict[str, Any]):
            return (s, self._extract(self._session_text(s.get("turns", []))))

        with ThreadPoolExecutor(max_workers=workers) as ex:
            extracted = list(ex.map(extract_one, sessions))

        added: List[Tuple[int, str]] = []
        for s, facts in extracted:
            added.extend(self._store(facts, s.get("thread_id"), s.get("captured_at"), None))
        return added
