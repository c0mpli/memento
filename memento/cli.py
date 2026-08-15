"""Memento CLI:  memento <command>

    init      create ~/.memento, the DB, and default config; print next steps
    capture   run the background capture daemon (foreground; used by LaunchAgent)
    start     install + load the LaunchAgent so capture runs 24x7 at login
    stop      unload the LaunchAgent
    restart   stop then start
    status    memory stats + whether the daemon is loaded
    mcp       run the MCP server over stdio (used by Claude Code / Codex)
    review    run the agent once now (find + auto-close open loops)
    search    keyword/semantic search from the terminal
    recent    show recent captures
    threads   list active threads
    loops     list open loops (--all also shows auto-closed)
    doctor    check environment + permissions
    tail      tail the daemon log

All output is emitted as structured events:  CODE_AREA_STATUS ,{json}
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, config, db
from .events import emit

AGENT_PROVIDERS = ("none", "claude_cli", "codex_cli", "anthropic", "openai", "ollama")
EMBED_PROVIDERS = ("none", "ollama", "openai")
_DEFAULT_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}

LABEL = "com.memento.agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>memento.cli</string>
        <string>capture</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
    <key>WorkingDirectory</key><string>{cwd}</string>
</dict>
</plist>
"""


def _ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


def _open_db():
    conn = db.get_conn(config.DB_PATH)
    db.init_db(conn)
    return conn


# --- lifecycle -------------------------------------------------------------

def cmd_init(args) -> int:
    config.ensure_base()
    _open_db().close()

    cfg = config.load_config()
    detected = None
    if (cfg.get("agent", {}).get("provider") or "none") == "none":
        if shutil.which("claude"):
            cfg["agent"]["provider"] = "claude_cli"
            detected = "claude_cli"
        elif shutil.which("codex"):
            cfg["agent"]["provider"] = "codex_cli"
            detected = "codex_cli"
    config.save_config(cfg)

    emit("MEMENTO_INIT_OK",
         data_dir=str(config.BASE_DIR), db=str(config.DB_PATH),
         config=str(config.CONFIG_PATH), agent=cfg["agent"]["provider"],
         detected=detected)
    emit("MEMENTO_INIT_NEXT",
         steps=["grant Accessibility to your terminal",
                "memento start",
                "claude mcp add memento -- memento mcp"])
    return 0


def cmd_capture(args) -> int:
    from . import daemon
    return daemon.run()


def cmd_mcp(args) -> int:
    from . import mcp_server
    mcp_server.main()
    return 0


def _write_plist() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.ensure_base()
    PLIST_PATH.write_text(PLIST_TEMPLATE.format(
        label=LABEL, python=sys.executable, log=str(config.LOG_PATH),
        cwd=str(config.BASE_DIR)))


def cmd_start(args) -> int:
    _write_plist()
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    r = subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        emit("MEMENTO_DAEMON_LOAD_ERR", error=r.stderr.strip())
        return 1
    emit("MEMENTO_DAEMON_LOADED", label=LABEL, log=str(config.LOG_PATH))
    return 0


def cmd_stop(args) -> int:
    if not PLIST_PATH.exists():
        emit("MEMENTO_DAEMON_ABSENT", label=LABEL)
        return 0
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    emit("MEMENTO_DAEMON_UNLOADED", label=LABEL)
    return 0


def cmd_restart(args) -> int:
    cmd_stop(args)
    return cmd_start(args)


def _is_loaded() -> bool:
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    return LABEL in r.stdout


def cmd_status(args) -> int:
    conn = _open_db()
    s = db.stats(conn)
    conn.close()
    emit("MEMENTO_STATUS_OK",
         version=__version__, loaded=_is_loaded(), threads=s["threads"],
         versions=s["versions"], embeddings=s["embeddings"],
         last_capture=_ts(s["last_capture"]) if s["last_capture"] else None,
         db=str(config.DB_PATH))
    return 0


# --- agent -----------------------------------------------------------------

def cmd_review(args) -> int:
    from . import agent
    cfg = config.load_config()
    provider = cfg.get("agent", {}).get("provider") or "none"
    if provider == "none":
        emit("MEMENTO_REVIEW_SKIP", reason="agent disabled", config=str(config.CONFIG_PATH))
        return 1
    conn = _open_db()
    emit("MEMENTO_REVIEW_START", provider=provider, window_minutes=args.minutes)
    r = agent.run_agent_once(cfg, conn, window_minutes=args.minutes)
    conn.close()
    emit("MEMENTO_REVIEW_DONE", provider=provider, new=r["new"], resolved=r["resolved"])
    return 0


# --- config ----------------------------------------------------------------

def cmd_config_show(args) -> int:
    cfg = config.load_config()
    emit("MEMENTO_CONFIG_SHOW", agent=cfg["agent"], embeddings=cfg["embeddings"],
         capture_interval_seconds=cfg["capture_interval_seconds"],
         watchlist=cfg["watchlist"], config=str(config.CONFIG_PATH))
    return 0


def cmd_config_agent(args) -> int:
    cfg = config.load_config()
    a = cfg["agent"]
    a["provider"] = args.provider
    if args.model is not None:
        a["model"] = args.model
    if args.endpoint is not None:
        a["endpoint"] = args.endpoint
    if args.command is not None:
        a["command"] = shlex.split(args.command)
    if args.interval is not None:
        a["interval_seconds"] = args.interval
    # Key-based providers: default the env var name and warn if it's unset.
    if args.provider in _DEFAULT_KEY_ENV:
        a["api_key_env"] = args.key_env or a.get("api_key_env") or _DEFAULT_KEY_ENV[args.provider]
    elif args.key_env is not None:
        a["api_key_env"] = args.key_env
    config.save_config(cfg)
    emit("MEMENTO_CONFIG_SET", section="agent", provider=a["provider"],
         model=a["model"], api_key_env=a["api_key_env"])
    if args.provider in _DEFAULT_KEY_ENV and not os.environ.get(a["api_key_env"], ""):
        emit("MEMENTO_CONFIG_HINT", note="set your key: export {}=...".format(a["api_key_env"]))
    return 0


def cmd_config_embeddings(args) -> int:
    cfg = config.load_config()
    e = cfg["embeddings"]
    e["provider"] = args.provider
    if args.model is not None:
        e["model"] = args.model
    if args.endpoint is not None:
        e["endpoint"] = args.endpoint
    if args.provider == "openai":
        e["api_key_env"] = args.key_env or e.get("api_key_env") or "OPENAI_API_KEY"
    elif args.key_env is not None:
        e["api_key_env"] = args.key_env
    config.save_config(cfg)
    emit("MEMENTO_CONFIG_SET", section="embeddings", provider=e["provider"],
         model=e["model"], api_key_env=e["api_key_env"])
    return 0


# --- reads -----------------------------------------------------------------

def cmd_search(args) -> int:
    conn = _open_db()
    rows = db.search(conn, args.query, limit=args.limit)
    conn.close()
    for r in rows:
        emit("MEMENTO_SEARCH_ROW", ts=_ts(r["captured_at"]), app=r["app"],
             text=(r["content"] or "").replace("\n", " ")[:200])
    emit("MEMENTO_SEARCH_DONE", query=args.query, count=len(rows))
    return 0


def cmd_recent(args) -> int:
    conn = _open_db()
    rows = db.recent(conn, limit=args.limit, minutes=args.minutes)
    conn.close()
    for r in rows:
        emit("MEMENTO_RECENT_ROW", ts=_ts(r["captured_at"]), app=r["app"],
             text=(r["content"] or "").replace("\n", " ")[:200])
    emit("MEMENTO_RECENT_DONE", count=len(rows), minutes=args.minutes)
    return 0


def cmd_threads(args) -> int:
    conn = _open_db()
    rows = db.list_threads(conn, limit=args.limit)
    conn.close()
    for r in rows:
        emit("MEMENTO_THREAD_ROW", id=r["id"], app=r["app"],
             title=(r["title"] or "")[:100], versions=r["version_count"],
             last_seen=_ts(r["last_seen"]))
    emit("MEMENTO_THREAD_DONE", count=len(rows))
    return 0


def cmd_loops(args) -> int:
    from . import agent
    conn = _open_db()
    items = agent.open_items(conn, limit=args.limit)
    for i in items:
        emit("MEMENTO_LOOP_OPEN", id=i["id"], title=i["title"],
             detail=i["detail"] or "", source_app=i["source_app"] or "")
    if args.all:
        for i in agent.resolved_items(conn, limit=args.limit):
            emit("MEMENTO_LOOP_CLOSED", id=i["id"], title=i["title"],
                 evidence=i["resolution_evidence"] or "", resolved_at=_ts(i["resolved_at"]))
    conn.close()
    emit("MEMENTO_LOOP_DONE", open=len(items))
    return 0


# --- diagnostics -----------------------------------------------------------

def cmd_doctor(args) -> int:
    ok = True
    emit("MEMENTO_DOCTOR_CHECK", name="python", status="ok", detail=sys.version.split()[0])
    try:
        import mcp  # noqa: F401
        emit("MEMENTO_DOCTOR_CHECK", name="mcp", status="ok", detail="installed")
    except Exception:
        ok = False
        emit("MEMENTO_DOCTOR_CHECK", name="mcp", status="missing", detail="pip install mcp")
    r = subprocess.run(["osascript", "-e",
                        'tell application "System Events" to get name of first '
                        'application process whose frontmost is true'],
                       capture_output=True, text=True)
    if r.returncode == 0:
        emit("MEMENTO_DOCTOR_CHECK", name="accessibility", status="ok", detail=r.stdout.strip())
    else:
        ok = False
        emit("MEMENTO_DOCTOR_CHECK", name="accessibility", status="denied",
             detail=r.stderr.strip() or "grant Accessibility to your terminal")
    cfg = config.load_config()
    emit("MEMENTO_DOCTOR_CHECK", name="agent", status="info",
         detail=cfg.get("agent", {}).get("provider"))
    emit("MEMENTO_DOCTOR_CHECK", name="embeddings", status="info",
         detail=cfg.get("embeddings", {}).get("provider"))
    emit("MEMENTO_DOCTOR_CHECK", name="daemon", status="info",
         detail="loaded" if _is_loaded() else "not loaded")
    emit("MEMENTO_DOCTOR_DONE", ok=ok)
    return 0 if ok else 1


def cmd_tail(args) -> int:
    if not config.LOG_PATH.exists():
        emit("MEMENTO_TAIL_EMPTY", log=str(config.LOG_PATH))
        return 0
    for ln in config.LOG_PATH.read_text(errors="replace").splitlines()[-args.n:]:
        print(ln)  # already structured events written by the daemon
    return 0


# --- parser ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memento", description="Local-first ambient memory for your Mac.")
    p.add_argument("-V", "--version", action="version", version="memento " + __version__)
    sub = p.add_subparsers(dest="cmd")

    for name in ("init", "capture", "mcp", "start", "stop", "restart", "status", "doctor"):
        sub.add_parser(name).set_defaults(func=globals()["cmd_" + name])

    sp = sub.add_parser("review"); sp.add_argument("--minutes", type=int, default=120); sp.set_defaults(func=cmd_review)
    sp = sub.add_parser("search"); sp.add_argument("query"); sp.add_argument("--limit", type=int, default=10); sp.set_defaults(func=cmd_search)
    sp = sub.add_parser("recent"); sp.add_argument("--minutes", type=int, default=None); sp.add_argument("--limit", type=int, default=20); sp.set_defaults(func=cmd_recent)
    sp = sub.add_parser("threads"); sp.add_argument("--limit", type=int, default=20); sp.set_defaults(func=cmd_threads)
    sp = sub.add_parser("loops"); sp.add_argument("--limit", type=int, default=50); sp.add_argument("--all", action="store_true", help="also show auto-closed loops"); sp.set_defaults(func=cmd_loops)
    sp = sub.add_parser("tail"); sp.add_argument("-n", type=int, default=40); sp.set_defaults(func=cmd_tail)

    # config: switch the agent/embeddings provider (e.g. to API keys) in one line
    cfgp = sub.add_parser("config", help="show or change providers/keys")
    csub = cfgp.add_subparsers(dest="section")
    csub.add_parser("show").set_defaults(func=cmd_config_show)
    ca = csub.add_parser("agent", help="e.g. memento config agent --provider anthropic")
    ca.add_argument("--provider", required=True, choices=AGENT_PROVIDERS)
    ca.add_argument("--model"); ca.add_argument("--key-env", dest="key_env")
    ca.add_argument("--endpoint"); ca.add_argument("--command",
                    help='override CLI argv, e.g. "claude -p {prompt}"')
    ca.add_argument("--interval", type=int); ca.set_defaults(func=cmd_config_agent)
    ce = csub.add_parser("embeddings", help="e.g. memento config embeddings --provider ollama")
    ce.add_argument("--provider", required=True, choices=EMBED_PROVIDERS)
    ce.add_argument("--model"); ce.add_argument("--key-env", dest="key_env")
    ce.add_argument("--endpoint"); ce.set_defaults(func=cmd_config_embeddings)
    cfgp.set_defaults(func=cmd_config_show)  # bare `memento config` -> show
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
