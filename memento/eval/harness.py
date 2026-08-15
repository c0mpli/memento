"""Per-case evaluation with the full retrieval pipeline.

Each case's haystack sessions are ingested as raw turns (recall backup) and
distilled into atomic facts (primary retrieval unit). We then retrieve with
decomposition + time-awareness + rerank, answer with the agent, and grade with
the agent as judge. Flags allow ablating each stage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from ..agents import create_named_agent, parse_json_object
from ..config import prompts
from ..core import database
from ..repository import DerivativeRepository, MemoryRepository
from ..services import embeddings
from ..services.derivation import DerivationService
from ..services.retrieval import RetrievalService
from ..types import EmbedProvider


def _parse_ts(date_str: str, index: int) -> float:
    if date_str:
        try:
            return datetime.strptime(str(date_str)[:10], "%Y/%m/%d").replace(
                tzinfo=timezone.utc).timestamp()
        except Exception:
            pass
    return float(index * 86400)


def evaluate_case(case: Dict[str, Any], cfg: Dict[str, Any], agent, top_k: int = 10,
                  use_facts: bool = True, decompose: bool = True,
                  time_aware: bool = True, rerank: bool = True) -> Dict[str, Any]:
    conn = database.get_conn(":memory:")
    database.init_db(conn)
    mem = MemoryRepository(conn)
    emb_on = (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value

    dates = case.get("haystack_dates") or []
    sessions = []
    for i, session in enumerate(case.get("haystack_sessions", [])):
        ts = _parse_ts(dates[i] if i < len(dates) else "", i)
        title = "session {}".format(i)
        for j, turn in enumerate(session):
            content = turn.get("content", "")
            if content:
                mem.record_capture(turn.get("role", "user"), title, content, ts=ts + j * 0.001)
        sessions.append({"turns": session, "captured_at": ts})

    if use_facts:
        added = DerivationService(conn, cfg).ingest_sessions(sessions, workers=8)
        if emb_on and added:
            vecs = embeddings.embed_texts(cfg, [c for _, c in added])
            drepo = DerivativeRepository(conn)
            for (did, _), vec in zip(added, vecs):
                if vec:
                    drepo.store_embedding(did, vec)

    rc = cfg.get("retrieval") or {}
    ret_agent = (create_named_agent(rc["provider"], rc.get("model", ""), rc.get("api_key_env", ""))
                 if rc.get("provider") else agent)
    rsvc = RetrievalService(conn, cfg, agent=ret_agent)
    if use_facts:
        rows = rsvc.retrieve(case["question"], as_of=case.get("question_date"), top_k=top_k,
                             decompose=decompose, time_aware=time_aware, rerank=rerank)
        context = rsvc.context(rows)
    else:
        # baseline: raw turns only
        rows = (rsvc.mem.semantic_search(rsvc._qvec(case["question"]), limit=top_k)
                if rsvc._qvec(case["question"]) else rsvc.mem.search(case["question"], limit=top_k))
        context = rsvc.context(rows)

    question = case["question"]
    predicted = (agent.complete(prompts.build_qa_prompt(context, question)) or "").strip()
    verdict = parse_json_object(
        agent.complete(prompts.build_judge_prompt(question, case.get("answer", ""), predicted)))
    conn.close()

    return {
        "question_id": case.get("question_id"),
        "question_type": case.get("question_type", "unknown"),
        "correct": bool(verdict.get("correct")),
        "retrieved": len(rows),
        "predicted": predicted[:200],
    }
