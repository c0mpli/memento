"""RetrievalService — the smart-retrieval pipeline.

    question
      -> time-window parse (restrict to a date range when the question is time-scoped)
      -> decompose into sub-questions (multi-hop)
      -> per sub-question: semantic/keyword search over FACTS (+ raw-turn recall backup)
      -> merge, rerank by relevance
      -> structured, timestamped context

Facts are the primary unit (high precision); raw turns are a recall backup. All
steps degrade gracefully, so retrieval always returns something.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..agents import create_agent, parse_json_object
from ..config import prompts
from ..repository import DerivativeRepository, MemoryRepository
from ..types import EmbedProvider
from . import embeddings


def _iso_to_epoch(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return "?"


class RetrievalService:
    def __init__(self, conn: sqlite3.Connection, cfg: Dict[str, Any], agent=None):
        self.cfg = cfg
        self.mem = MemoryRepository(conn)
        self.deriv = DerivativeRepository(conn)
        self.agent = agent or create_agent(cfg.get("agent", {}))

    def _emb_on(self) -> bool:
        return (self.cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value

    def _qvec(self, query: str) -> Optional[List[float]]:
        return embeddings.embed_text(self.cfg, query) if self._emb_on() else None

    # ---- pipeline steps ----

    def time_window(self, question: str, as_of: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
        if not self.agent or not as_of:
            return (None, None)
        try:
            v = parse_json_object(self.agent.complete(
                prompts.build_time_expansion_prompt(question, as_of)))
        except Exception:
            return (None, None)
        return (_iso_to_epoch(v.get("from")), _iso_to_epoch(v.get("to")))

    def decompose(self, question: str) -> List[str]:
        if not self.agent:
            return [question]
        try:
            v = parse_json_object(self.agent.complete(prompts.build_decomposition_prompt(question)))
            subs = [str(s).strip() for s in (v.get("subquestions") or []) if str(s).strip()]
        except Exception:
            subs = []
        return subs[:4] or [question]

    def _fact_hits(self, query: str, k: int, tf, tt) -> List[Dict[str, Any]]:
        qv = self._qvec(query)
        if qv:
            rows = self.deriv.semantic_search(qv, limit=k, time_from=tf, time_to=tt)
            if rows:
                return rows
        return self.deriv.keyword_search(query, limit=k, time_from=tf, time_to=tt)

    def rerank(self, question: str, cands: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        if not self.agent or len(cands) <= top_k:
            return cands[:top_k]
        listing = "\n".join("[{}] {}".format(i, (c.get("content") or "")[:200])
                            for i, c in enumerate(cands))
        try:
            v = parse_json_object(self.agent.complete(prompts.build_rerank_prompt(question, listing)))
            order = [int(x) for x in (v.get("order") or []) if str(x).lstrip("-").isdigit()]
        except Exception:
            order = []
        picked, seen = [], set()
        for i in order:
            if 0 <= i < len(cands) and i not in seen:
                picked.append(cands[i])
                seen.add(i)
        for i, c in enumerate(cands):
            if i not in seen:
                picked.append(c)
        return picked[:top_k]

    def retrieve(self, question: str, as_of: Optional[str] = None, top_k: int = 10,
                 decompose: bool = True, time_aware: bool = True,
                 rerank: bool = True) -> List[Dict[str, Any]]:
        tf, tt = self.time_window(question, as_of) if time_aware else (None, None)
        subs = self.decompose(question) if decompose else [question]

        pool: Dict[Any, Dict[str, Any]] = {}
        for sub in subs:
            for r in self._fact_hits(sub, top_k, tf, tt):
                pool[("f", r["id"])] = r
        # recall backup: raw turns (keyword) for the whole question
        for r in self.mem.search(question, limit=top_k):
            key = ("v", r.get("id"))
            pool.setdefault(key, r)

        cands = list(pool.values())
        return self.rerank(question, cands, top_k) if rerank else cands[:top_k]

    def context(self, rows: List[Dict[str, Any]]) -> str:
        return "\n".join("[{}] {}".format(_fmt_ts(r.get("captured_at")),
                                          (r.get("content") or "").strip())
                         for r in rows) or "(nothing retrieved)"
