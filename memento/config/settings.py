"""Paths and user-configurable settings.

Everything Memento owns lives under ~/.memento:
    memento.db      the local SQLite memory store
    config.json     user configuration (DEFAULTS below, overridable)
    memento.log     capture daemon log
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from ..types import AgentProvider, EmbedProvider

HOME = Path(os.path.expanduser("~"))
BASE_DIR = Path(os.environ.get("MEMENTO_HOME", HOME / ".memento"))
DB_PATH = BASE_DIR / "memento.db"
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "memento.log"

# LaunchAgent + MCP tunables.
LAUNCH_LABEL = "com.memento.agent"       # headless capture daemon
MENUBAR_LABEL = "com.memento.menubar"    # menu-bar app (open loops)
MCP_DEFAULT_HOST = "127.0.0.1"
MCP_DEFAULT_PORT = 8787

# Privacy-first defaults. A capture tool should refuse to look at secrets by
# default, so the sensitive excludes live here rather than as an opt-out.
DEFAULTS: Dict[str, Any] = {
    "capture_interval_seconds": 15,
    "exclude_apps": [
        "1Password", "1Password 7", "1Password 8", "Bitwarden", "KeePassXC",
        "Dashlane", "LastPass", "Keychain Access", "Passwords",
    ],
    "exclude_title_keywords": [
        "password", "passcode", "login", "sign in", "sign-in", "otp",
        "one-time", "verification code", "bank", "routing", "ssn", "secret",
        "private browsing", "incognito",
    ],
    "capture_clipboard": False,
    "watchlist": [],
    # Semantic search provider (keyword search is the zero-cost default).
    "embeddings": {
        "provider": EmbedProvider.NONE.value,
        "model": "",
        "endpoint": "http://127.0.0.1:11434",
        "api_key_env": "",
    },
    # The background open-loops agent. Reuses your claude/codex CLI (no key) by
    # default; `memento init` auto-detects and enables it.
    "agent": {
        "provider": AgentProvider.NONE.value,
        "command": [],          # override CLI argv; "{prompt}" is substituted
        "model": "",
        "endpoint": "http://127.0.0.1:11434",
        "api_key_env": "",
        "interval_seconds": 3600,
        "window_minutes": 90,
    },
}


def ensure_base() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    """Load config, deep-merging saved values over DEFAULTS so new keys appear."""
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text())
        except (ValueError, OSError):
            saved = {}
        _deep_merge(cfg, saved)
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    ensure_base()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
