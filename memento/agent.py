"""The background agent — the part that DOES the work, like Minimi.

Two jobs, run together on each tick over your recent memory:

  1. FIND open loops  — commitments / follow-ups / tasks you still owe.
  2. CLOSE them        — when later activity shows a loop was resolved, mark it
                         done automatically (with the evidence), no manual effort.

It reuses the assistant you already pay for. Set agent.provider to:
  claude_cli | codex_cli   -> shells out to your CLI (no API key)
  anthropic | openai | ollama -> uses a key / local model

Disabled by default; `memento init` auto-enables it if `claude`/`codex` is found.
stdlib-only; degrades gracefully (returns 0) on any error.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from typing import Any, Dict, List

from . import db as _db
from .notify import notify

ACTION_ITEMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_items (
    id                  INTEGER PRIMARY KEY,
    title               TEXT NOT NULL,
    detail              TEXT,
    source_app          TEXT,
    status              TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    resolution_evidence TEXT,
    created_at          REAL NOT NULL,
    resolved_at         REAL,
    fingerprint         TEXT NOT NULL UNIQUE
);
"""

PROMPT_HEADER = (
    "You maintain a user's OPEN LOOPS — commitments, promises, follow-ups, or "
    "tasks they still need to act on — from a log of their recent computer "
    "activity.\n\n"
    "You are given (1) the CURRENTLY OPEN LOOPS with ids, and (2) RECENT "
    "ACTIVITY (newest first). Do two things:\n"
    "A. FIND new open loops clearly supported by the activity and not already "
    "in the open list.\n"
    "B. CLOSE any currently-open loop that the activity shows was completed or "
    "resolved.\n\n"
    "Return ONLY a JSON object, no prose:\n"
    '{"new_loops":[{"title":"short imperative","detail":"one sentence of '
    'context","source_app":"app"}],"resolved":[{"id":123,"evidence":"why it is '
    'done"}]}\n'
    "Use [] for empty. Never invent items unsupported by the activity.\n"
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ACTION_ITEMS_SCHEMA)
    conn.commit()


def run_agent_once(cfg: Dict[str, Any], conn: sqlite3.Connection,
                   window_minutes: int = None) -> Dict[str, int]:
    """Returns {"new": int, "resolved": int}."""
    ac = cfg.get("agent", {})
    provider = (ac.get("provider") or "none").lower()
    if provider == "none":
        return {"new": 0, "resolved": 0}
    ensure_schema(conn)
    if window_minutes is None:
        window_minutes = int(ac.get("window_minutes", 90))

    rows = _db.recent(conn, limit=150, minutes=window_minutes)
    if not rows:
        return {"new": 0, "resolved": 0}

    open_now = open_items(conn, limit=100)
    open_block = "\n".join("  #{}: {}".format(i["id"], i["title"]) for i in open_now) or "  (none)"
    log = "\n".join(
        "- [{}] {}".format(r["app"], (r["content"] or "").replace("\n", " ")[:200])
        for r in rows
    )
    prompt = "{}\nCURRENTLY OPEN LOOPS:\n{}\n\nRECENT ACTIVITY:\n{}\n".format(
        PROMPT_HEADER, open_block, log)

    try:
        result = _call(provider, ac, prompt)
    except Exception:
        return {"new": 0, "resolved": 0}
    if not isinstance(result, dict):
        return {"new": 0, "resolved": 0}

    now = time.time()
    new_count = 0
    for it in result.get("new_loops") or []:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        fp = _db.fingerprint("action", title)
        try:
            conn.execute(
                "INSERT INTO action_items (title, detail, source_app, created_at, fingerprint) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, str(it.get("detail") or "").strip(),
                 str(it.get("source_app") or "").strip(), now, fp),
            )
            new_count += 1
        except sqlite3.IntegrityError:
            pass  # already tracking this loop

    resolved_count = 0
    open_ids = {i["id"] for i in open_now}
    for it in result.get("resolved") or []:
        if not isinstance(it, dict):
            continue
        try:
            iid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if iid not in open_ids:
            continue
        cur = conn.execute(
            "UPDATE action_items SET status='resolved', resolved_at=?, "
            "resolution_evidence=? WHERE id=? AND status='open'",
            (now, str(it.get("evidence") or "").strip(), iid),
        )
        if cur.rowcount and cur.rowcount > 0:
            resolved_count += 1
    conn.commit()

    if new_count or resolved_count:
        notify(
            "Memento: +{} open loop(s), {} auto-closed".format(new_count, resolved_count),
            "Ask your assistant: what are my open loops?",
        )
    return {"new": new_count, "resolved": resolved_count}


def open_items(conn: sqlite3.Connection, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT id, title, detail, source_app, created_at FROM action_items "
        "WHERE status='open' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def resolved_items(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT id, title, resolution_evidence, resolved_at FROM action_items "
        "WHERE status='resolved' ORDER BY resolved_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- provider dispatch ----

def _call(provider: str, ac: Dict[str, Any], prompt: str) -> Any:
    if provider in ("claude_cli", "codex_cli", "cli"):
        defaults = {
            "claude_cli": ["claude", "-p", "{prompt}"],
            "codex_cli": ["codex", "exec", "{prompt}"],
            "cli": ["claude", "-p", "{prompt}"],
        }
        return _cli_call(ac, prompt, defaults[provider])
    if provider == "anthropic":
        return _anthropic(ac, prompt)
    if provider == "openai":
        return _openai(ac, prompt)
    if provider == "ollama":
        return _ollama(ac, prompt)
    return {}


def _cli_call(ac: Dict[str, Any], prompt: str, default_argv: List[str]) -> Any:
    argv = ac.get("command") or default_argv
    if any("{prompt}" in a for a in argv):
        argv = [a.replace("{prompt}", prompt) for a in argv]
        stdin = None
    else:
        stdin = prompt  # no placeholder -> feed on stdin
    try:
        out = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    if out.returncode != 0:
        return {}
    return _parse_json_object(out.stdout)


def _post(url: str, payload: Dict[str, Any], headers: Dict[str, str],
          timeout: float = 60.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _anthropic(ac: Dict[str, Any], prompt: str) -> Any:
    key = os.environ.get(ac.get("api_key_env") or "ANTHROPIC_API_KEY", "")
    if not key:
        return {}
    out = _post(
        "https://api.anthropic.com/v1/messages",
        {"model": ac.get("model") or "claude-sonnet-4-5", "max_tokens": 1024,
         "messages": [{"role": "user", "content": prompt}]},
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return _parse_json_object("".join(b.get("text", "") for b in out.get("content", [])))


def _openai(ac: Dict[str, Any], prompt: str) -> Any:
    key = os.environ.get(ac.get("api_key_env") or "OPENAI_API_KEY", "")
    if not key:
        return {}
    out = _post(
        "https://api.openai.com/v1/chat/completions",
        {"model": ac.get("model") or "gpt-4o-mini",
         "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": "Bearer " + key},
    )
    return _parse_json_object(out["choices"][0]["message"]["content"])


def _ollama(ac: Dict[str, Any], prompt: str) -> Any:
    endpoint = (ac.get("endpoint") or "http://127.0.0.1:11434").rstrip("/")
    out = _post(
        endpoint + "/api/chat",
        {"model": ac.get("model") or "llama3.1", "stream": False,
         "messages": [{"role": "user", "content": prompt}]},
        {},
    )
    return _parse_json_object(out.get("message", {}).get("content", ""))


def _parse_json_object(text: str) -> Any:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}
