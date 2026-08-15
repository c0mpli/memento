"""The background capture daemon — the always-on part.

Runs under a macOS LaunchAgent. Every interval it samples the frontmost window,
dedups it into the store via the repository, optionally embeds it, fires
watchlist notifications, and periodically runs the open-loops service.
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
from ..types import Event, EmbedProvider
from . import capture, embeddings
from .notifications import notify
from .open_loops import OpenLoopsService

_RUNNING = True


def _handle_stop(signum, frame):  # noqa: ANN001
    global _RUNNING
    _RUNNING = False


def _emit(code: str, **data: Any) -> None:
    """Write one structured event to the log file and stdout."""
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

    cfg = load_config()
    conn = database.connect()
    memory = MemoryRepository(conn)
    loops = OpenLoopsService(conn, cfg)

    interval = max(2, int(cfg.get("capture_interval_seconds", 15)))
    agent_provider = cfg.get("agent", {}).get("provider") or "none"
    agent_interval = int(cfg.get("agent", {}).get("interval_seconds", 3600))
    embed_on = (cfg.get("embeddings", {}).get("provider") or "none") != EmbedProvider.NONE.value

    _emit(Event.DAEMON_START.value, interval=interval, embeddings=embed_on, agent=agent_provider)

    last_agent = 0.0
    while _RUNNING:
        loop_start = time.time()
        try:
            cap = capture.capture_once(cfg)
            if cap:
                res = memory.record_capture(cap["app"], cap["title"], cap["content"])
                if res["stored"]:
                    _watch(cfg, cap)
                    if embed_on and res["version_id"] is not None:
                        vec = embeddings.embed_text(cfg, cap["content"])
                        if vec:
                            memory.store_embedding(res["version_id"], vec)

            if loops.agent is not None and (loop_start - last_agent) >= agent_interval:
                last_agent = loop_start
                try:
                    r = loops.run_once()
                    if r["new"] or r["resolved"]:
                        _emit(Event.AGENT_RUN.value, new=r["new"], resolved=r["resolved"])
                except Exception as e:  # noqa: BLE001
                    _emit(Event.AGENT_ERR.value, error=str(e))
        except Exception as e:  # noqa: BLE001
            _emit(Event.CAPTURE_ERR.value, error=str(e))

        elapsed = time.time() - loop_start
        remaining = interval - elapsed
        while remaining > 0 and _RUNNING:
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

    _emit(Event.DAEMON_STOP.value)
    conn.close()
    return 0
