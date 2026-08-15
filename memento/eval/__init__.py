"""LongMemEval-style accuracy harness.

    memento eval [--dataset PATH] [--limit N] [--top-k K]

Scores retrieval + QA accuracy per question type, the same six categories the
memory benchmarks report (single-session-user/assistant/preference,
knowledge-update, temporal-reasoning, multi-session).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..agents import create_agent
from ..core.logger import emit
from ..types import Event
from .dataset import load_dataset
from .harness import evaluate_case


def run_eval(cfg: Dict[str, Any], dataset_path: Optional[str] = None,
             limit: Optional[int] = None, top_k: int = 8, use_facts: bool = True,
             decompose: bool = True, time_aware: bool = True,
             rerank: bool = True) -> Dict[str, Any]:
    agent = create_agent(cfg.get("agent", {}))
    if agent is None:
        emit(Event.REVIEW_SKIP.value, reason="agent disabled")
        return {"overall": 0.0, "per_type": {}, "n": 0}

    cases = load_dataset(dataset_path)
    if limit:
        cases = cases[:limit]

    per: Dict[str, list] = {}
    for c in cases:
        try:
            r = evaluate_case(c, cfg, agent, top_k=top_k, use_facts=use_facts,
                              decompose=decompose, time_aware=time_aware, rerank=rerank)
        except Exception as e:  # noqa: BLE001
            r = {"question_id": c.get("question_id"),
                 "question_type": c.get("question_type", "unknown"),
                 "correct": False, "retrieved": 0, "predicted": "", "error": str(e)}
        emit(Event.EVAL_CASE.value, id=r["question_id"], type=r["question_type"],
             correct=r["correct"], retrieved=r.get("retrieved", 0))
        b = per.setdefault(r["question_type"], [0, 0])
        b[1] += 1
        b[0] += 1 if r["correct"] else 0

    scores = {t: round(100.0 * a / n, 1) for t, (a, n) in per.items() if n}
    correct = sum(a for a, _ in per.values())
    total = sum(n for _, n in per.values())
    overall = round(100.0 * correct / total, 1) if total else 0.0
    emit(Event.EVAL_DONE.value, overall=overall, n=total, per_type=scores)
    return {"overall": overall, "per_type": scores, "n": total}
