"""Per-case evaluation: ingest → retrieve → answer → judge.

Each case is ingested into a fresh in-memory DB (its haystack sessions become
memory), then we run Memento's own retrieval, answer with the configured agent,
and grade the answer with the same agent as an LLM judge. This is exactly the
path the product uses, so the score reflects real end-to-end quality.
"""

from __future__ import annotations

from typing import Any, Dict

from ..agents import create_agent, parse_json_object
from ..config import prompts
from ..core import database
from ..repository import MemoryRepository
from ..services import embeddings
from ..types import EmbedProvider


def _retrieve(mem: MemoryRepository, cfg: Dict[str, Any], question: str, top_k: int):
    if (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value:
        qv = embeddings.embed_text(cfg, question)
        if qv:
            rows = mem.semantic_search(qv, limit=top_k)
            if rows:
                return rows
    return mem.search(question, limit=top_k)


def evaluate_case(case: Dict[str, Any], cfg: Dict[str, Any],
                  agent, top_k: int = 8) -> Dict[str, Any]:
    conn = database.get_conn(":memory:")
    database.init_db(conn)
    mem = MemoryRepository(conn)
    embed_on = (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value

    dates = case.get("haystack_dates") or []
    for i, session in enumerate(case.get("haystack_sessions", [])):
        date = dates[i] if i < len(dates) else ""
        title = "session {}{}".format(i, " " + date if date else "")
        for j, turn in enumerate(session):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if not content:
                continue
            res = mem.record_capture(role, title, content, ts=float(i * 1000 + j))
            if embed_on and res["stored"] and res["version_id"] is not None:
                vec = embeddings.embed_text(cfg, content)
                if vec:
                    mem.store_embedding(res["version_id"], vec)

    question = case["question"]
    rows = _retrieve(mem, cfg, question, top_k)
    context = "\n".join(
        "[{} | {}] {}".format(r.get("app", "?"), (r.get("title") or "").strip(),
                              (r.get("content") or "").strip())
        for r in rows
    ) or "(nothing retrieved)"

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
