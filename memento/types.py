"""Enumerations used across Memento.

Using `str`-backed enums means members compare/serialise as their string value
(so they drop straight into JSON, argparse choices, and SQLite) while still
giving us a single source of truth and IDE/refactor safety.
"""

from __future__ import annotations

from enum import Enum


class AgentProvider(str, Enum):
    """Who runs the open-loops agent."""
    NONE = "none"
    CLAUDE_CLI = "claude_cli"   # reuse your Claude Code subscription (no key)
    CODEX_CLI = "codex_cli"     # reuse your Codex subscription (no key)
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"           # fully local


class EmbedProvider(str, Enum):
    """Who computes embeddings for semantic search."""
    NONE = "none"
    OLLAMA = "ollama"
    OPENAI = "openai"
    GEMINI = "gemini"


class ItemStatus(str, Enum):
    """State of an open loop / action item."""
    OPEN = "open"
    RESOLVED = "resolved"


class Transport(str, Enum):
    """MCP transport."""
    STDIO = "stdio"
    HTTP = "streamable-http"


# Default env var holding the API key, per key-based provider.
DEFAULT_KEY_ENV = {
    AgentProvider.ANTHROPIC.value: "ANTHROPIC_API_KEY",
    AgentProvider.OPENAI.value: "OPENAI_API_KEY",
    AgentProvider.GEMINI.value: "GEMINI_API_KEY",
}


class Event(str, Enum):
    """Structured event codes (CODE_AREA_STATUS)."""
    # lifecycle
    INIT_OK = "MEMENTO_INIT_OK"
    INIT_NEXT = "MEMENTO_INIT_NEXT"
    DAEMON_START = "MEMENTO_DAEMON_START"
    DAEMON_STOP = "MEMENTO_DAEMON_STOP"
    DAEMON_LOADED = "MEMENTO_DAEMON_LOADED"
    DAEMON_UNLOADED = "MEMENTO_DAEMON_UNLOADED"
    DAEMON_ABSENT = "MEMENTO_DAEMON_ABSENT"
    DAEMON_LOAD_ERR = "MEMENTO_DAEMON_LOAD_ERR"
    STATUS_OK = "MEMENTO_STATUS_OK"
    # agent
    AGENT_RUN = "MEMENTO_AGENT_RUN"
    AGENT_ERR = "MEMENTO_AGENT_ERR"
    CAPTURE_ERR = "MEMENTO_CAPTURE_ERR"
    REVIEW_START = "MEMENTO_REVIEW_START"
    REVIEW_DONE = "MEMENTO_REVIEW_DONE"
    REVIEW_SKIP = "MEMENTO_REVIEW_SKIP"
    # config
    CONFIG_SHOW = "MEMENTO_CONFIG_SHOW"
    CONFIG_SET = "MEMENTO_CONFIG_SET"
    CONFIG_HINT = "MEMENTO_CONFIG_HINT"
    # reads
    SEARCH_ROW = "MEMENTO_SEARCH_ROW"
    SEARCH_DONE = "MEMENTO_SEARCH_DONE"
    RECENT_ROW = "MEMENTO_RECENT_ROW"
    RECENT_DONE = "MEMENTO_RECENT_DONE"
    THREAD_ROW = "MEMENTO_THREAD_ROW"
    THREAD_DONE = "MEMENTO_THREAD_DONE"
    LOOP_OPEN = "MEMENTO_LOOP_OPEN"
    LOOP_CLOSED = "MEMENTO_LOOP_CLOSED"
    LOOP_DONE = "MEMENTO_LOOP_DONE"
    # mcp
    MCP_HTTP = "MEMENTO_MCP_HTTP"
    # diagnostics
    DOCTOR_CHECK = "MEMENTO_DOCTOR_CHECK"
    DOCTOR_DONE = "MEMENTO_DOCTOR_DONE"
    TAIL_EMPTY = "MEMENTO_TAIL_EMPTY"
    # eval
    EVAL_CASE = "MEMENTO_EVAL_CASE"
    EVAL_RETRIEVAL = "MEMENTO_EVAL_RETRIEVAL"
    EVAL_LOOPS = "MEMENTO_EVAL_LOOPS"
    EVAL_DONE = "MEMENTO_EVAL_DONE"
