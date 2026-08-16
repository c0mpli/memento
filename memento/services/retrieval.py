"""RetrievalService — the retrieval pipeline.

Design:
  - the retrievable VALUE is the raw round (verbatim), so no detail is lost;
    facts only augment the embedded KEY at index time (done during ingestion).
  - multi-hop questions are decomposed into sub-questions.
  - per sub-question we fuse semantic + keyword rankings with Reciprocal Rank
    Fusion, so both signals contribute.
  - time-awareness is a SOFT boost (in-range rounds float up) rather than a hard
    filter, so a mis-parsed window can't drop the answer.
  - candidates are reranked, then sorted oldest->newest for the reader.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..agents import create_agent, parse_json_object
from ..config import prompts
from ..repository import MemoryRepository
from ..types import EmbedProvider
from . import embeddings

RRF_K = 60


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


def _rid(r: Dict[str, Any]) -> Any:
    return r.get("id", r.get("version_id"))


class RetrievalService:
    def __init__(self, conn: sqlite3.Connection, cfg: Dict[str, Any], agent=None):
        self.cfg = cfg
        self.mem = MemoryRepository(conn)
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

    def _semantic(self, query: str, n: int) -> List[Dict[str, Any]]:
        qv = self._qvec(query)
        if qv:
            rows = self.mem.semantic_search(qv, limit=n)
            if rows:
                return rows
        return self.mem.search(query, limit=n)

    def _time_hint(self, tf, tt) -> str:
        if tf is None and tt is None:
            return ""
        return " (relevant dates {} to {})".format(_fmt_ts(tf) if tf else "?",
                                                    _fmt_ts(tt) if tt else "?")

    def _fuse(self, question: str, subs: List[str], n: int, time_hint: str = "") -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion of semantic + keyword lists across sub-questions.
        The semantic query is expanded with the resolved date range; keyword uses
        the original words."""
        scores: Dict[Any, float] = {}
        rows: Dict[Any, Dict[str, Any]] = {}
        for sub in subs:
            for rank, r in enumerate(self._semantic(sub + time_hint, n)):
                k = _rid(r)
                scores[k] = scores.get(k, 0.0) + 1.0 / (RRF_K + rank)
                rows.setdefault(k, r)
            for rank, r in enumerate(self.mem.search(sub, limit=n)):
                k = _rid(r)
                scores[k] = scores.get(k, 0.0) + 1.0 / (RRF_K + rank)
                rows.setdefault(k, r)
        order = sorted(scores, key=lambda k: scores[k], reverse=True)
        return [rows[k] for k in order]

    def _cap_per_session(self, rows: List[Dict[str, Any]], per: int = 2) -> List[Dict[str, Any]]:
        """Force cross-session coverage: at most `per` rounds per session."""
        seen: Dict[Any, int] = {}
        out = []
        for r in rows:
            key = r.get("title") or r.get("app") or _rid(r)
            if seen.get(key, 0) < per:
                out.append(r)
                seen[key] = seen.get(key, 0) + 1
        return out

    def _time_boost(self, cands: List[Dict[str, Any]], tf, tt) -> List[Dict[str, Any]]:
        if tf is None and tt is None:
            return cands
        def in_range(r):
            ts = r.get("captured_at")
            if ts is None:
                return False
            return (tf is None or ts >= tf) and (tt is None or ts <= tt)
        inside = [r for r in cands if in_range(r)]
        outside = [r for r in cands if not in_range(r)]
        return inside + outside  # soft: in-range first, nothing dropped

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
        cands = self._fuse(question, subs, n=top_k * 3, time_hint=self._time_hint(tf, tt))
        cands = self._time_boost(cands, tf, tt)
        cands = cands[:max(top_k * 2, top_k)]
        cands = self.rerank(question, cands, top_k) if rerank else cands[:top_k]
        cands.sort(key=lambda r: r.get("captured_at") or 0.0)  # reader: oldest -> newest
        return cands

    def context(self, rows: List[Dict[str, Any]]) -> str:
        return "\n".join("[{}] {}".format(_fmt_ts(r.get("captured_at")),
                                          (r.get("content") or "").strip())
                         for r in rows) or "(nothing retrieved)"
