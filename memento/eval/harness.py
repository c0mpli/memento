"""Per-case evaluation with the K = V + fact retrieval pipeline.

The retrievable value is the raw round (verbatim). Facts extracted from each
session only augment the embedded key, so retrieval recall improves without
losing the detail the reader needs. Reading is Chain-of-Note (scratchpad then
'ANSWER:'), and the agent judges the answer. Flags ablate each stage.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


def _question_ts(date_str: str) -> Optional[float]:
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str)[:10], "%Y/%m/%d").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def _fmt_date(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def _compile_profile(prefs_by_session: List[List[Dict[str, str]]]) -> List[str]:
    """Deduplicated, chronological list of all preference statements (no cap)."""
    out, seen = [], set()
    for prefs in prefs_by_session:
        for p in prefs:
            s = str(p.get("statement") or "").strip()
            key = s.lower()
            if s and key not in seen:
                seen.add(key)
                out.append(s)
    return out


def _select_profile(all_prefs: List[str], question: str, cfg: Dict[str, Any],
                    k: int = 20) -> List[str]:
    """Preferences relevant to the question (semantic), so the right one is
    always present even across a huge history; falls back to the full list."""
    if len(all_prefs) <= k:
        return all_prefs
    emb_on = (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value
    if not emb_on:
        return all_prefs[-k:]
    qv = embeddings.embed_text(cfg, question)
    vecs = embeddings.embed_texts(cfg, all_prefs)
    if not qv:
        return all_prefs[-k:]
    import math
    qn = math.sqrt(sum(x * x for x in qv)) or 1.0
    scored = []
    for pref, v in zip(all_prefs, vecs):
        if not v:
            continue
        dot = sum(a * b for a, b in zip(qv, v))
        vn = math.sqrt(sum(x * x for x in v)) or 1.0
        scored.append((dot / (qn * vn), pref))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:k]]


def _reader_context(profile: List[str], rows: List[Dict[str, Any]],
                    as_of_ts: Optional[float]) -> str:
    prof = "KNOWN USER PREFERENCES:\n" + (
        "\n".join("- " + p for p in profile) if profile else "(none recorded)")
    items = []
    for r in rows:
        ts = r.get("captured_at")
        days_ago = int((as_of_ts - ts) // 86400) if (as_of_ts and ts is not None) else None
        items.append({"date": _fmt_date(ts), "days_ago": days_ago,
                      "text": (r.get("content") or "").strip()[:600]})
    return prof + "\n\nMEMORIES:\n" + json.dumps(items, ensure_ascii=False)


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
    # preferences form a durable profile that is always injected at read time.
    session_facts: List[List[str]] = [[] for _ in sessions]
    profile: List[str] = []
    if use_facts:
        items = DerivationService(conn, cfg).items_for_sessions(sessions, workers=8)
        session_facts = [[str(d.get("content") or "").strip() for d in sess if d.get("content")]
                         for sess in items]
        prefs_by_session = [[{"statement": d.get("content", "")} for d in sess
                             if d.get("kind") == "preference"] for sess in items]
        profile = _select_profile(_compile_profile(prefs_by_session), case["question"], cfg, k=20)

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
    context = _reader_context(profile, rows, _question_ts(case.get("question_date", "")))

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
