"""Per-case evaluation with the K = V + fact retrieval pipeline.

The retrievable value is the raw round (verbatim). Facts extracted from each
session only augment the embedded key, so retrieval recall improves without
losing the detail the reader needs. Reading is Chain-of-Note (scratchpad then
'ANSWER:'), and the agent judges the answer. Flags ablate each stage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from ..agents import create_named_agent, parse_json_object
from ..config import prompts
from ..core import database
from ..repository import MemoryRepository
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


def _rounds(session: List[Dict[str, Any]]) -> List[str]:
    """Pair consecutive user/assistant turns into rounds (the value unit)."""
    rounds, i = [], 0
    while i < len(session):
        t = session[i]
        nxt = session[i + 1] if i + 1 < len(session) else None
        if nxt and t.get("role") == "user" and nxt.get("role") == "assistant":
            rounds.append("user: {}\nassistant: {}".format(
                t.get("content", ""), nxt.get("content", "")))
            i += 2
        else:
            rounds.append("{}: {}".format(t.get("role", "user"), t.get("content", "")))
            i += 1
    return rounds


def _extract_answer(raw: str) -> str:
    text = (raw or "").strip()
    marker = text.lower().rfind("answer:")
    return text[marker + len("answer:"):].strip() if marker != -1 else text


def evaluate_case(case: Dict[str, Any], cfg: Dict[str, Any], agent, top_k: int = 10,
                  use_facts: bool = True, decompose: bool = True,
                  time_aware: bool = True, rerank: bool = True) -> Dict[str, Any]:
    conn = database.get_conn(":memory:")
    database.init_db(conn)
    mem = MemoryRepository(conn)
    emb_on = (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value

    sessions = case.get("haystack_sessions", [])
    dates = case.get("haystack_dates") or []

    # facts augment the KEY only (K = V + fact); values stay verbatim.
    session_facts: List[List[str]] = [[] for _ in sessions]
    if use_facts and emb_on:
        session_facts = DerivationService(conn, cfg).facts_for_sessions(sessions, workers=8)

    pending = []  # (version_id, key_text)
    for i, session in enumerate(sessions):
        ts = _parse_ts(dates[i] if i < len(dates) else "", i)
        facts = " ".join(session_facts[i]) if i < len(session_facts) else ""
        for k, round_text in enumerate(_rounds(session)):
            res = mem.record_capture("chat", "session {}".format(i), round_text, ts=ts + k * 0.001)
            if emb_on and res["stored"] and res["version_id"] is not None:
                key_text = round_text + ("\nfacts: " + facts if facts else "")
                pending.append((res["version_id"], key_text))

    if emb_on and pending:
        vecs = embeddings.embed_texts(cfg, [kt for _, kt in pending])
        for (vid, _), vec in zip(pending, vecs):
            if vec:
                mem.store_embedding(vid, vec)

    rc = cfg.get("retrieval") or {}
    ret_agent = (create_named_agent(rc["provider"], rc.get("model", ""), rc.get("api_key_env", ""))
                 if rc.get("provider") else agent)
    rsvc = RetrievalService(conn, cfg, agent=ret_agent)
    rows = rsvc.retrieve(case["question"], as_of=case.get("question_date"), top_k=top_k,
                         decompose=decompose, time_aware=time_aware, rerank=rerank)
    context = rsvc.context(rows)

    question = case["question"]
    predicted = _extract_answer(agent.complete(prompts.build_qa_prompt(context, question)))
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
