"""The background capture daemon — the always-on part.

Runs under a macOS LaunchAgent. Every interval it samples the frontmost window,
dedups it into the store via the repository, optionally embeds it, fires
watchlist notifications, and periodically runs the open-loops service.

Config is re-read every tick, so changes from the menu bar (provider, API key,
pause) apply live without a restart.
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from typing import Any, Dict

from ..config import load_config, settings
from ..core import database, logger
from ..repository import MemoryRepository
from ..types import EmbedProvider, Event
from ..sources import capture_once
from . import embeddings
from .notifications import notify
from .open_loops import OpenLoopsService

_RUNNING = True


def _handle_stop(signum, frame):  # noqa: ANN001
    global _RUNNING
    _RUNNING = False


def _emit(code: str, **data: Any) -> None:
    s = logger.line(code, ts=datetime.now().isoformat(timespec="seconds"), **data)
    try:
        with open(settings.LOG_PATH, "a") as f:
            f.write(s + "\n")
    except OSError:
        pass
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def _watch(cfg: Dict[str, Any], cap: Dict[str, str]) -> None:
    hay = ("{} {}".format(cap["app"], cap["content"])).lower()
    for term in cfg.get("watchlist", []):
        if term and term.lower() in hay:
            notify("Memento: {}".format(term), "{} — {}".format(cap["app"], cap["title"][:80]))


def run() -> int:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    conn = database.connect()
    memory = MemoryRepository(conn)
    _emit(Event.DAEMON_START.value)

    last_agent = 0.0
    while _RUNNING:
        loop_start = time.time()
        cfg = load_config()  # live: menu-bar changes apply immediately
        interval = max(2, int(cfg.get("capture_interval_seconds", 15)))
        embed_on = (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value
        agent_interval = int(cfg.get("agent", {}).get("interval_seconds", 3600))
        agent_on = (cfg.get("agent", {}).get("provider") or "none") != "none"

        try:
            if not cfg.get("paused"):
                cap = capture_once(cfg)
                if cap:
                    res = memory.record_capture(cap["app"], cap["title"], cap["content"])
                    if res["stored"]:
                        _watch(cfg, cap)
                        if embed_on and res["version_id"] is not None:
                            vec = embeddings.embed_text(cfg, cap["content"])
                            if vec:
                                memory.store_embedding(res["version_id"], vec)

            if agent_on and (loop_start - last_agent) >= agent_interval:
                last_agent = loop_start
                try:
                    r = OpenLoopsService(conn, cfg).run_once()
                    if r["new"] or r["resolved"]:
                        _emit(Event.AGENT_RUN.value, new=r["new"], resolved=r["resolved"])
                except Exception as e:  # noqa: BLE001
                    _emit(Event.AGENT_ERR.value, error=str(e))
        except Exception as e:  # noqa: BLE001
            _emit(Event.CAPTURE_ERR.value, error=str(e))

        elapsed = time.time() - loop_start
        remaining = interval - elapsed
        while remaining > 0 and _RUNNING:
            time.sleep(min(1.0, remaining))
            remaining -= 1.0

    _emit(Event.DAEMON_STOP.value)
    conn.close()
    return 0
