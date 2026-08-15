"""The background capture daemon — this is the always-on part.

Runs under a macOS LaunchAgent (login-launched, KeepAlive). Every
`capture_interval_seconds` it samples the frontmost window, dedups it into the
memory store, optionally embeds it, fires watchlist notifications, and — if the
optional agent is configured — periodically extracts open loops.

Memento is ambient: it builds memory over time in the background. It is NOT a
one-shot "what's on screen right now" — that history is the whole point.
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from typing import Any, Dict

from . import agent, capture, config, db, embed
from .events import line
from .notify import notify

_RUNNING = True


def _handle_stop(signum, frame):  # noqa: ANN001
    global _RUNNING
    _RUNNING = False


def _emit(code: str, **data) -> None:
    """Write one structured event to the log file and stdout."""
    s = line(code, ts=datetime.now().isoformat(timespec="seconds"), **data)
    try:
        with open(config.LOG_PATH, "a") as f:
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

    config.ensure_base()
    cfg = config.load_config()
    conn = db.get_conn(config.DB_PATH)
    db.init_db(conn)

    interval = max(2, int(cfg.get("capture_interval_seconds", 15)))
    agent_provider = (cfg.get("agent", {}).get("provider") or "none").lower()
    agent_interval = int(cfg.get("agent", {}).get("interval_seconds", 3600))
    embed_on = (cfg.get("embeddings", {}).get("provider") or "none").lower() != "none"

    _emit("MEMENTO_DAEMON_START", interval=interval, embeddings=embed_on,
          agent=agent_provider)

    last_agent = 0.0
    while _RUNNING:
        loop_start = time.time()
        try:
            cap = capture.capture_once(cfg)
            if cap:
                res = db.record_capture(conn, cap["app"], cap["title"], cap["content"])
                if res["stored"]:
                    _watch(cfg, cap)
                    if embed_on and res["version_id"] is not None:
                        vec = embed.embed_text(cfg, cap["content"])
                        if vec:
                            db.store_embedding(conn, res["version_id"], vec)

            if agent_provider != "none" and (loop_start - last_agent) >= agent_interval:
                last_agent = loop_start
                try:
                    r = agent.run_agent_once(cfg, conn)
                    if r["new"] or r["resolved"]:
                        _emit("MEMENTO_AGENT_RUN", new=r["new"], resolved=r["resolved"])
                except Exception as e:  # noqa: BLE001
                    _emit("MEMENTO_AGENT_ERR", error=str(e))
        except Exception as e:  # noqa: BLE001
            _emit("MEMENTO_CAPTURE_ERR", error=str(e))

        # Sleep the remainder of the interval, but stay responsive to signals.
        elapsed = time.time() - loop_start
        remaining = interval - elapsed
        while remaining > 0 and _RUNNING:
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

    _emit("MEMENTO_DAEMON_STOP")
    conn.close()
    return 0
