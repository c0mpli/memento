"""Lightweight entity graph + Personalized PageRank for cross-session retrieval.

Built from extracted entities: each round contributes its session's entities as
nodes; entities co-occurring in a round are linked. At query time we seed PPR
from the question's entities (IDF-weighted) and score rounds by the PageRank
mass over their nodes. This surfaces evidence spread across sessions that no
single embedding ranks well (the multi-session case). Pure in-memory numpy.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Dict, List

import numpy as np

_TOK = re.compile(r"[a-z0-9]+")
_NUMERIC = re.compile(r"^\d")


def _norm(phrase: str) -> str:
    return " ".join(_TOK.findall((phrase or "").lower()))


class EntityGraph:
    def __init__(self, max_nodes: int = 4000):
        self.node_id: Dict[str, int] = {}
        self.phrases: List[str] = []
        self.round_nodes: Dict[int, set] = defaultdict(set)
        self.node_rounds: Dict[int, set] = defaultdict(set)
        self.co: Dict[tuple, float] = defaultdict(float)
        self.max_nodes = max_nodes
        self._M = None
        self._idf = None

    def _node(self, phrase: str):
        p = _norm(phrase)
        if not p or len(p) < 2:
            return None
        if p not in self.node_id:
            if len(self.phrases) >= self.max_nodes:
                return None
            self.node_id[p] = len(self.phrases)
            self.phrases.append(p)
        return self.node_id[p]

    def add_round(self, round_id: int, entities: List[str]) -> None:
        ids = sorted({n for n in (self._node(e) for e in entities) if n is not None})
        for n in ids:
            self.round_nodes[round_id].add(n)
            self.node_rounds[n].add(round_id)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                self.co[(ids[i], ids[j])] += 1.0

    def finalize(self, total_rounds: int) -> None:
        n = len(self.phrases)
        if n == 0:
            return
        self._idf = np.array(
            [math.log((total_rounds + 1) / (1 + len(self.node_rounds[i]))) + 1.0
             for i in range(n)], dtype=np.float32)
        a = np.zeros((n, n), dtype=np.float32)
        for (x, y), w in self.co.items():
            a[x, y] += w
            a[y, x] += w
        col = a.sum(axis=0)
        col[col == 0] = 1.0
        self._M = a / col

    def _seed_nodes(self, question: str) -> np.ndarray:
        n = len(self.phrases)
        e = np.zeros(n, dtype=np.float32)
        qtokens = set(_TOK.findall(question.lower()))
        qnorm = " " + " ".join(_TOK.findall(question.lower())) + " "
        for phrase, idx in self.node_id.items():
            # seed if the whole entity phrase appears in the question, or a
            # distinctive (non-numeric, len>=4) token of it does
            hit = (" " + phrase + " ") in qnorm
            if not hit:
                for tok in phrase.split():
                    if len(tok) >= 4 and not _NUMERIC.match(tok) and tok in qtokens:
                        hit = True
                        break
            if hit:
                e[idx] += float(self._idf[idx])
        return e

    def rank_rounds(self, question: str, top_n: int = 10,
                    alpha: float = 0.5, iters: int = 20) -> List[int]:
        if self._M is None or not self.phrases:
            return []
        e = self._seed_nodes(question)
        if e.sum() == 0:
            return []
        e = e / e.sum()
        p = e.copy()
        for _ in range(iters):
            p = alpha * e + (1.0 - alpha) * (self._M @ p)
        scores: Dict[int, float] = defaultdict(float)
        nz = np.nonzero(p)[0]
        for node in nz:
            mass = float(p[node])
            for rid in self.node_rounds[int(node)]:
                scores[rid] += mass
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [rid for rid, _ in ranked[:top_n]]
