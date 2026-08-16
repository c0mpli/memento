"""DerivationService — distill raw activity into atomic facts.

Extraction (an LLM call) is the expensive part, so it can run concurrently; the
SQLite writes stay on one thread. In the product this runs in the background on
newly-committed versions; the eval uses it to index each haystack session.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from ..agents import create_agent, create_named_agent, parse_json_array
from ..config import prompts
from ..repository import DerivativeRepository

# Optional on-disk extraction cache (keyed by conversation hash). Enabled by the
# MEMENTO_EXTRACT_CACHE env var; used by the eval so shared sessions are extracted
# once. Class-level so it is shared across DerivationService instances in a run.
_CACHE: Optional[Dict[str, Any]] = None
_CACHE_PATH: Optional[str] = None
_CACHE_LOCK = threading.Lock()
_CACHE_DIRTY = False


def _cache_init() -> None:
    global _CACHE, _CACHE_PATH
    path = os.environ.get("MEMENTO_EXTRACT_CACHE")
    if path and _CACHE is None:
        _CACHE_PATH = path
        try:
            _CACHE = json.loads(open(path).read())
        except Exception:
            _CACHE = {}


def _cache_flush() -> None:
    global _CACHE_DIRTY
    if _CACHE is not None and _CACHE_PATH and _CACHE_DIRTY:
        with _CACHE_LOCK:
            try:
                tmp = _CACHE_PATH + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(_CACHE, f)
                os.replace(tmp, _CACHE_PATH)
                _CACHE_DIRTY = False
            except Exception:
                pass


class DerivationService:
    def __init__(self, conn: sqlite3.Connection, cfg: Dict[str, Any], agent=None):
        self.cfg = cfg
        self.repo = DerivativeRepository(conn)
        self.agent = agent or self._build_agent(cfg)
        _cache_init()

    @staticmethod
    def _build_agent(cfg: Dict[str, Any]):
        dc = cfg.get("derivation") or {}
        if dc.get("provider"):
            return create_named_agent(dc["provider"], dc.get("model", ""), dc.get("api_key_env", ""))
        return create_agent(cfg.get("agent", {}))

    def _extract(self, conversation: str) -> List[Dict[str, Any]]:
        global _CACHE_DIRTY
        if not self.agent or not conversation.strip():
            return []
        key = None
        if _CACHE is not None:
            key = hashlib.sha256(conversation.encode("utf-8", "replace")).hexdigest()
            with _CACHE_LOCK:
                if key in _CACHE:
                    return _CACHE[key]
        try:
            result = parse_json_array(self.agent.complete(prompts.build_extraction_prompt(conversation)))
        except Exception:
            result = []
        if key is not None:
            with _CACHE_LOCK:
                _CACHE[key] = result
                _CACHE_DIRTY = True
        return result

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

    def session_items(self, turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """One extraction pass -> all items (facts + preferences + events)."""
        return [f for f in self._extract(self._session_text(turns))
                if isinstance(f, dict) and str(f.get("content") or "").strip()]

    def items_for_sessions(self, sessions: List[List[Dict[str, Any]]],
                           workers: int = 8) -> List[List[Dict[str, Any]]]:
        """Extract items for many sessions concurrently; order preserved."""
        with ThreadPoolExecutor(max_workers=workers) as ex:
            out = list(ex.map(self.session_items, sessions))
        _cache_flush()
        return out

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
