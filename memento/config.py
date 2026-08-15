"""Paths and configuration for Memento.

Everything Memento owns lives under ~/.memento:
    memento.db      the local SQLite memory store
    config.json     user configuration (this module's DEFAULTS, overridable)
    memento.log     capture daemon log
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

HOME = Path(os.path.expanduser("~"))
BASE_DIR = Path(os.environ.get("MEMENTO_HOME", HOME / ".memento"))
DB_PATH = BASE_DIR / "memento.db"
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "memento.log"

# Sensible, privacy-first defaults. A capture tool should refuse to look at
# secrets by default — mirror that here rather than making the user opt out.
DEFAULTS: Dict[str, Any] = {
    "capture_interval_seconds": 15,
    # Never capture these apps at all.
    "exclude_apps": [
        "1Password", "1Password 7", "1Password 8", "Bitwarden", "KeePassXC",
        "Dashlane", "LastPass", "Keychain Access", "Passwords",
    ],
    # Skip a capture if the window title looks sensitive.
    "exclude_title_keywords": [
        "password", "passcode", "login", "sign in", "sign-in", "otp",
        "one-time", "verification code", "bank", "routing", "ssn", "secret",
        "private browsing", "incognito",
    ],
    # Optionally fold the clipboard into a capture (off by default — noisy/sensitive).
    "capture_clipboard": False,
    # Substrings that, when newly seen in a title/content, fire a macOS notification.
    "watchlist": [],
    # Optional semantic search. provider: none | ollama | openai
    #   ollama:  local & free, e.g. model "nomic-embed-text", endpoint "http://127.0.0.1:11434"
    #   openai:  set model "text-embedding-3-small" and api_key_env "OPENAI_API_KEY"
    "embeddings": {
        "provider": "none",
        "model": "",
        "endpoint": "http://127.0.0.1:11434",
        "api_key_env": "",
    },
    # The background agent — the part that DOES what Minimi does (extract open
    # loops, follow-ups) instead of waiting to be asked. It reuses the CLI you
    # already pay for, so NO API key is needed:
    #   claude_cli : shells out to Claude Code   -> ["claude", "-p", "{prompt}"]
    #   codex_cli  : shells out to Codex          -> ["codex", "exec", "{prompt}"]
    # Key-based providers also work: anthropic | openai | ollama.
    # `memento init` auto-detects a `claude`/`codex` binary and enables this.
    "agent": {
        "provider": "none",
        "command": [],          # override the CLI argv; "{prompt}" is substituted
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
