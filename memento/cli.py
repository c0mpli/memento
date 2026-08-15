"""Memento CLI:  memento <command>

    init      create ~/.memento, the DB, and default config; print next steps
    capture   run the background capture daemon (foreground; used by LaunchAgent)
    start     install + load the LaunchAgent so capture runs 24x7 at login
    stop      unload the LaunchAgent
    restart   stop then start
    status    memory stats + whether the daemon is loaded
    mcp       run the MCP server (stdio, or --http for custom connectors)
    review    run the agent once now (find + auto-close open loops)
    config    show or change providers/keys
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

from . import __version__, config
from .core import database
from .core.logger import emit
from .repository import ActionItemRepository, MemoryRepository
from .types import DEFAULT_KEY_ENV, AgentProvider, EmbedProvider, Event, Transport

AGENT_PROVIDERS = tuple(p.value for p in AgentProvider)
EMBED_PROVIDERS = tuple(p.value for p in EmbedProvider)

LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"

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
        <string>memento</string>
        <string>{sub}</string>
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


def _plist_path(label: str) -> Path:
    return LAUNCH_AGENTS / (label + ".plist")


def _rumps_available() -> bool:
    try:
        import rumps  # noqa: F401
        return True
    except Exception:
        return False


def _ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


# --- lifecycle -------------------------------------------------------------

def cmd_init(args) -> int:
    config.ensure_base()
    database.connect().close()

    cfg = config.load_config()
    detected = None
    if (cfg.get("agent", {}).get("provider") or "none") == AgentProvider.NONE.value:
        if shutil.which("claude"):
            cfg["agent"]["provider"] = AgentProvider.CLAUDE_CLI.value
            detected = AgentProvider.CLAUDE_CLI.value
        elif shutil.which("codex"):
            cfg["agent"]["provider"] = AgentProvider.CODEX_CLI.value
            detected = AgentProvider.CODEX_CLI.value
    config.save_config(cfg)

    emit(Event.INIT_OK.value, data_dir=str(config.BASE_DIR), db=str(config.DB_PATH),
         config=str(config.CONFIG_PATH), agent=cfg["agent"]["provider"], detected=detected)
    emit(Event.INIT_NEXT.value, steps=["grant Accessibility to your terminal",
                                       "memento start",
                                       "claude mcp add memento -- memento mcp"])
    return 0


def cmd_capture(args) -> int:
    from .services.daemon import run
    return run()


def cmd_menubar(args) -> int:
    try:
        import rumps  # noqa: F401
    except Exception as e:  # noqa: BLE001
        emit(Event.MENUBAR_MISSING.value, error=str(e),
             hint="pip install 'memento-memory[menubar]'")
        return 1
    from .services import menubar
    emit(Event.MENUBAR_START.value)
    return menubar.run()


def cmd_mcp(args) -> int:
    from .mcp import server
    if getattr(args, "http", False):
        emit(Event.MCP_HTTP.value, url="http://{}:{}/mcp".format(args.host, args.port),
             transport=Transport.HTTP.value)
        server.main(Transport.HTTP.value, host=args.host, port=args.port)
    else:
        server.main()
    return 0


def _agents() -> list:
    """LaunchAgents to run by default: headless capture + the menu-bar app."""
    agents = [(config.LAUNCH_LABEL, "capture")]
    if _rumps_available():
        agents.append((config.MENUBAR_LABEL, "menubar"))
    return agents


def _load_agent(label: str, sub: str) -> bool:
    path = _plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    config.ensure_base()
    path.write_text(PLIST_TEMPLATE.format(
        label=label, sub=sub, python=sys.executable,
        log=str(config.LOG_PATH), cwd=str(config.BASE_DIR)))
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    r = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        emit(Event.DAEMON_LOAD_ERR.value, label=label, error=r.stderr.strip())
        return False
    emit(Event.DAEMON_LOADED.value, label=label, kind=sub, log=str(config.LOG_PATH))
    return True


def cmd_start(args) -> int:
    ok = True
    for label, sub in _agents():
        ok = _load_agent(label, sub) and ok
    return 0 if ok else 1


def cmd_stop(args) -> int:
    for label in (config.LAUNCH_LABEL, config.MENUBAR_LABEL):
        path = _plist_path(label)
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            emit(Event.DAEMON_UNLOADED.value, label=label)
        else:
            emit(Event.DAEMON_ABSENT.value, label=label)
    return 0


def cmd_restart(args) -> int:
    cmd_stop(args)
    return cmd_start(args)


def _is_loaded() -> bool:
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    return config.LAUNCH_LABEL in r.stdout


def cmd_status(args) -> int:
    conn = database.connect()
    s = MemoryRepository(conn).stats()
    conn.close()
    emit(Event.STATUS_OK.value, version=__version__, loaded=_is_loaded(),
         threads=s["threads"], versions=s["versions"], embeddings=s["embeddings"],
         last_capture=_ts(s["last_capture"]) if s["last_capture"] else None,
         db=str(config.DB_PATH))
    return 0


# --- agent -----------------------------------------------------------------

def cmd_review(args) -> int:
    from .services.open_loops import OpenLoopsService
    cfg = config.load_config()
    provider = cfg.get("agent", {}).get("provider") or "none"
    if provider == AgentProvider.NONE.value:
        emit(Event.REVIEW_SKIP.value, reason="agent disabled", config=str(config.CONFIG_PATH))
        return 1
    conn = database.connect()
    emit(Event.REVIEW_START.value, provider=provider, window_minutes=args.minutes)
    r = OpenLoopsService(conn, cfg).run_once(window_minutes=args.minutes)
    conn.close()
    emit(Event.REVIEW_DONE.value, provider=provider, new=r["new"], resolved=r["resolved"])
    return 0


# --- config ----------------------------------------------------------------

def cmd_config_show(args) -> int:
    cfg = config.load_config()
    emit(Event.CONFIG_SHOW.value, agent=cfg["agent"], embeddings=cfg["embeddings"],
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
    if args.provider in DEFAULT_KEY_ENV:
        a["api_key_env"] = args.key_env or a.get("api_key_env") or DEFAULT_KEY_ENV[args.provider]
    elif args.key_env is not None:
        a["api_key_env"] = args.key_env
    config.save_config(cfg)
    emit(Event.CONFIG_SET.value, section="agent", provider=a["provider"],
         model=a["model"], api_key_env=a["api_key_env"])
    if args.provider in DEFAULT_KEY_ENV and not os.environ.get(a["api_key_env"], ""):
        emit(Event.CONFIG_HINT.value, note="set your key: export {}=...".format(a["api_key_env"]))
    return 0


def cmd_config_embeddings(args) -> int:
    cfg = config.load_config()
    e = cfg["embeddings"]
    e["provider"] = args.provider
    if args.model is not None:
        e["model"] = args.model
    if args.endpoint is not None:
        e["endpoint"] = args.endpoint
    if args.provider in DEFAULT_KEY_ENV:
        e["api_key_env"] = args.key_env or e.get("api_key_env") or DEFAULT_KEY_ENV[args.provider]
    elif args.key_env is not None:
        e["api_key_env"] = args.key_env
    config.save_config(cfg)
    emit(Event.CONFIG_SET.value, section="embeddings", provider=e["provider"],
         model=e["model"], api_key_env=e["api_key_env"])
    return 0


# --- reads -----------------------------------------------------------------

def cmd_search(args) -> int:
    conn = database.connect()
    rows = MemoryRepository(conn).search(args.query, limit=args.limit)
    conn.close()
    for r in rows:
        emit(Event.SEARCH_ROW.value, ts=_ts(r["captured_at"]), app=r["app"],
             text=(r["content"] or "").replace("\n", " ")[:200])
    emit(Event.SEARCH_DONE.value, query=args.query, count=len(rows))
    return 0


def cmd_recent(args) -> int:
    conn = database.connect()
    rows = MemoryRepository(conn).recent(limit=args.limit, minutes=args.minutes)
    conn.close()
    for r in rows:
        emit(Event.RECENT_ROW.value, ts=_ts(r["captured_at"]), app=r["app"],
             text=(r["content"] or "").replace("\n", " ")[:200])
    emit(Event.RECENT_DONE.value, count=len(rows), minutes=args.minutes)
    return 0


def cmd_threads(args) -> int:
    conn = database.connect()
    rows = MemoryRepository(conn).list_threads(limit=args.limit)
    conn.close()
    for r in rows:
        emit(Event.THREAD_ROW.value, id=r["id"], app=r["app"],
             title=(r["title"] or "")[:100], versions=r["version_count"],
             last_seen=_ts(r["last_seen"]))
    emit(Event.THREAD_DONE.value, count=len(rows))
    return 0


def cmd_loops(args) -> int:
    conn = database.connect()
    items = ActionItemRepository(conn)
    for i in items.open_items(limit=args.limit):
        emit(Event.LOOP_OPEN.value, id=i["id"], title=i["title"],
             detail=i["detail"] or "", source_app=i["source_app"] or "")
    if args.all:
        for i in items.resolved_items(limit=args.limit):
            emit(Event.LOOP_CLOSED.value, id=i["id"], title=i["title"],
                 evidence=i["resolution_evidence"] or "", resolved_at=_ts(i["resolved_at"]))
    open_n = len(items.open_items(limit=args.limit))
    conn.close()
    emit(Event.LOOP_DONE.value, open=open_n)
    return 0


# --- diagnostics -----------------------------------------------------------

def cmd_doctor(args) -> int:
    ok = True
    emit(Event.DOCTOR_CHECK.value, name="python", status="ok", detail=sys.version.split()[0])
    try:
        import mcp  # noqa: F401
        emit(Event.DOCTOR_CHECK.value, name="mcp", status="ok", detail="installed")
    except Exception:
        ok = False
        emit(Event.DOCTOR_CHECK.value, name="mcp", status="missing", detail="pip install mcp")
    r = subprocess.run(["osascript", "-e",
                        'tell application "System Events" to get name of first '
                        'application process whose frontmost is true'],
                       capture_output=True, text=True)
    if r.returncode == 0:
        emit(Event.DOCTOR_CHECK.value, name="accessibility", status="ok", detail=r.stdout.strip())
    else:
        ok = False
        emit(Event.DOCTOR_CHECK.value, name="accessibility", status="denied",
             detail=r.stderr.strip() or "grant Accessibility to your terminal")
    cfg = config.load_config()
    emit(Event.DOCTOR_CHECK.value, name="agent", status="info",
         detail=cfg.get("agent", {}).get("provider"))
    emit(Event.DOCTOR_CHECK.value, name="embeddings", status="info",
         detail=cfg.get("embeddings", {}).get("provider"))
    emit(Event.DOCTOR_CHECK.value, name="daemon", status="info",
         detail="loaded" if _is_loaded() else "not loaded")
    emit(Event.DOCTOR_DONE.value, ok=ok)
    return 0 if ok else 1


def cmd_tail(args) -> int:
    if not config.LOG_PATH.exists():
        emit(Event.TAIL_EMPTY.value, log=str(config.LOG_PATH))
        return 0
    for ln in config.LOG_PATH.read_text(errors="replace").splitlines()[-args.n:]:
        print(ln)
    return 0


# --- parser ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memento", description="Local-first ambient memory for your Mac.")
    p.add_argument("-V", "--version", action="version", version="memento " + __version__)
    sub = p.add_subparsers(dest="cmd")

    for name in ("init", "capture", "menubar", "start", "stop", "restart", "status", "doctor"):
        sub.add_parser(name).set_defaults(func=globals()["cmd_" + name])

    mp = sub.add_parser("mcp")
    mp.add_argument("--http", action="store_true", help="serve over streamable-HTTP for custom connectors")
    mp.add_argument("--host", default=config.MCP_DEFAULT_HOST)
    mp.add_argument("--port", type=int, default=config.MCP_DEFAULT_PORT)
    mp.set_defaults(func=cmd_mcp)

    rp = sub.add_parser("review"); rp.add_argument("--minutes", type=int, default=120); rp.set_defaults(func=cmd_review)
    sp = sub.add_parser("search"); sp.add_argument("query"); sp.add_argument("--limit", type=int, default=10); sp.set_defaults(func=cmd_search)
    sp = sub.add_parser("recent"); sp.add_argument("--minutes", type=int, default=None); sp.add_argument("--limit", type=int, default=20); sp.set_defaults(func=cmd_recent)
    sp = sub.add_parser("threads"); sp.add_argument("--limit", type=int, default=20); sp.set_defaults(func=cmd_threads)
    sp = sub.add_parser("loops"); sp.add_argument("--limit", type=int, default=50); sp.add_argument("--all", action="store_true"); sp.set_defaults(func=cmd_loops)
    sp = sub.add_parser("tail"); sp.add_argument("-n", type=int, default=40); sp.set_defaults(func=cmd_tail)

    cfgp = sub.add_parser("config", help="show or change providers/keys")
    csub = cfgp.add_subparsers(dest="section")
    csub.add_parser("show").set_defaults(func=cmd_config_show)
    ca = csub.add_parser("agent", help="e.g. memento config agent --provider anthropic")
    ca.add_argument("--provider", required=True, choices=AGENT_PROVIDERS)
    ca.add_argument("--model"); ca.add_argument("--key-env", dest="key_env")
    ca.add_argument("--endpoint"); ca.add_argument("--command", help='override CLI argv, e.g. "claude -p {prompt}"')
    ca.add_argument("--interval", type=int); ca.set_defaults(func=cmd_config_agent)
    ce = csub.add_parser("embeddings", help="e.g. memento config embeddings --provider ollama")
    ce.add_argument("--provider", required=True, choices=EMBED_PROVIDERS)
    ce.add_argument("--model"); ce.add_argument("--key-env", dest="key_env")
    ce.add_argument("--endpoint"); ce.set_defaults(func=cmd_config_embeddings)
    cfgp.set_defaults(func=cmd_config_show)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
