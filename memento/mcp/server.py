"""MCP server — the surface Claude Code / Codex / any MCP client queries.

Exposes local memory as tools over stdio (default) or streamable-HTTP (for
"custom connector" clients like claude.ai / ChatGPT / Gemini). Run with
`memento mcp` (stdio) or `memento mcp --http`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from ..config import load_config
from ..core import database
from ..repository import ActionItemRepository, MemoryRepository
from ..services import embeddings
from ..types import EmbedProvider, Transport

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "The 'mcp' package is required for `memento mcp`.\n"
        "Install it:  pip install mcp   (or: uv sync)\n"
        "(original error: {})".format(exc)
    )

mcp = FastMCP("memento")


def _memory() -> MemoryRepository:
    return MemoryRepository(database.connect())


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def _fmt_rows(rows: List[dict]) -> str:
    if not rows:
        return "(no matching memories)"
    out = []
    for r in rows:
        score = " ({:.2f})".format(r["score"]) if "score" in r else ""
        content = (r.get("content") or "").replace("\n", " ").strip()
        out.append("[{}] {} — {}{}\n    {}".format(
            _fmt_ts(r.get("captured_at")), r.get("app", "?"),
            (r.get("title") or "").strip()[:100], score, content[:400]))
    return "\n".join(out)


@mcp.tool()
def search_memory(query: str, limit: int = 10) -> str:
    """Search the user's captured memory (apps, windows, docs, chats) by topic.
    Semantic when embeddings are configured, else keyword; newest-first ties."""
    cfg = load_config()
    repo = _memory()
    if (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value:
        qvec = embeddings.embed_text(cfg, query)
        if qvec:
            rows = repo.semantic_search(qvec, limit=limit)
            if rows:
                return _fmt_rows(rows)
    return _fmt_rows(repo.search(query, limit=limit))


@mcp.tool()
def recent_context(minutes: int = 30, limit: int = 20) -> str:
    """What the user has been doing in the last `minutes` — for
    'what am I working on', 'what was I just doing', 'catch me up'."""
    return _fmt_rows(_memory().recent(limit=limit, minutes=minutes))


@mcp.tool()
def list_threads(limit: int = 20) -> str:
    """List recently-active threads (one per app+window) with a preview."""
    rows = _memory().list_threads(limit=limit)
    if not rows:
        return "(no threads yet — is the memento daemon running? `memento status`)"
    return "\n".join(
        "#{} [{}] {} — {} versions, last {}\n    {}".format(
            r["id"], r["app"], (r["title"] or "").strip()[:80], r["version_count"],
            _fmt_ts(r["last_seen"]), (r.get("preview") or "").replace("\n", " ")[:200])
        for r in rows)


@mcp.tool()
def get_thread(thread_id: int, limit: int = 20) -> str:
    """Full recent version history of one thread by id (from list_threads)."""
    rows = _memory().thread_context(thread_id, limit=limit)
    if not rows:
        return "(no such thread or no versions)"
    return "\n".join("[{}] {}".format(_fmt_ts(r["captured_at"]),
                                      (r["content"] or "").replace("\n", " ")[:400])
                     for r in rows)


@mcp.tool()
def open_loops(limit: int = 50) -> str:
    """List open loops (commitments/follow-ups) found by the background agent."""
    items = ActionItemRepository(database.connect()).open_items(limit=limit)
    if not items:
        return "(no open loops recorded — the background agent may be disabled)"
    return "\n".join("• {}{}".format(i["title"], " — " + i["detail"] if i["detail"] else "")
                     for i in items)


def main(transport: str = Transport.STDIO.value,
         host: str = "127.0.0.1", port: int = 8787) -> None:
    if transport == Transport.HTTP.value:
        try:
            mcp.settings.host = host
            mcp.settings.port = port
        except Exception:
            pass
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
