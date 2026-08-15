"""MCP server — the surface Claude Code / Codex / any MCP client queries.

Exposes your local memory as tools over stdio. This is what lets the LLM you
already pay for read what you've been doing, with no cloud service in between.

Run standalone with `memento mcp`. Register with Claude Code:
    claude mcp add memento -- memento mcp
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from . import agent as _agent
from . import config, db, embed

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "The 'mcp' package is required for `memento mcp`.\n"
        "Install it:  pip install mcp\n"
        "(original error: {})".format(exc)
    )

mcp = FastMCP("memento")


def _conn():
    conn = db.get_conn(config.DB_PATH)
    db.init_db(conn)
    return conn


def _cfg():
    return config.load_config()


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def _fmt_rows(rows: List[dict]) -> str:
    if not rows:
        return "(no matching memories)"
    lines = []
    for r in rows:
        score = " ({:.2f})".format(r["score"]) if "score" in r else ""
        content = (r.get("content") or "").replace("\n", " ").strip()
        lines.append("[{}] {} — {}{}\n    {}".format(
            _fmt_ts(r.get("captured_at")), r.get("app", "?"),
            (r.get("title") or "").strip()[:100], score, content[:400]))
    return "\n".join(lines)


@mcp.tool()
def search_memory(query: str, limit: int = 10) -> str:
    """Search the user's captured memory (apps, windows, docs, chats) by topic.

    Uses semantic search when embeddings are configured, otherwise keyword
    search. Returns the most relevant captures, newest first for ties."""
    conn = _conn()
    cfg = _cfg()
    if (cfg.get("embeddings", {}).get("provider") or "none").lower() != "none":
        qvec = embed.embed_text(cfg, query)
        if qvec:
            rows = db.semantic_search(conn, qvec, limit=limit)
            if rows:
                return _fmt_rows(rows)
    return _fmt_rows(db.search(conn, query, limit=limit))


@mcp.tool()
def recent_context(minutes: int = 30, limit: int = 20) -> str:
    """What the user has been doing in the last `minutes`. Use this for
    'what am I working on', 'what was I just doing', 'catch me up'."""
    return _fmt_rows(db.recent(_conn(), limit=limit, minutes=minutes))


@mcp.tool()
def list_threads(limit: int = 20) -> str:
    """List recently-active threads (one per app+window identity) with a
    preview. Good for a broad overview before drilling in with search_memory."""
    rows = db.list_threads(_conn(), limit=limit)
    if not rows:
        return "(no threads yet — is the memento daemon running? `memento status`)"
    return "\n".join(
        "#{} [{}] {} — {} versions, last {}\n    {}".format(
            r["id"], r["app"], (r["title"] or "").strip()[:80], r["version_count"],
            _fmt_ts(r["last_seen"]), (r.get("preview") or "").replace("\n", " ")[:200])
        for r in rows
    )


@mcp.tool()
def get_thread(thread_id: int, limit: int = 20) -> str:
    """Full recent version history of one thread by id (from list_threads)."""
    rows = db.thread_context(_conn(), thread_id, limit=limit)
    if not rows:
        return "(no such thread or no versions)"
    return "\n".join("[{}] {}".format(_fmt_ts(r["captured_at"]),
                                      (r["content"] or "").replace("\n", " ")[:400])
                     for r in rows)


@mcp.tool()
def open_loops(limit: int = 50) -> str:
    """List open loops (commitments/follow-ups) found by the optional background
    agent. Empty unless the agent is configured in ~/.memento/config.json."""
    items = _agent.open_items(_conn(), limit=limit)
    if not items:
        return "(no open loops recorded — the background agent may be disabled)"
    return "\n".join("• {}{}".format(i["title"], " — " + i["detail"] if i["detail"] else "")
                     for i in items)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
