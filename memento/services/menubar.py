"""macOS menu-bar app — Memento's whole UI in one icon.

Click the icon (top-right, left of Wi-Fi) to:
  • see your open loops; click one to mark it done
  • "Review now" — run the agent on demand
  • pause / resume capture
  • Settings — pick your AI provider and paste an API key (stored in config)
  • Connect to Claude — copies the one-line MCP command

Built on `rumps` (a default macOS dependency).
"""

from __future__ import annotations

import subprocess
import threading

try:
    import rumps
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "The 'rumps' package is required for the menu bar.\n"
        "Install it:  pip install 'memento-memory[menubar]'\n"
        "(original error: {})".format(exc)
    )

from ..config import load_config, save_config
from ..core import database
from ..repository import ActionItemRepository
from ..types import DEFAULT_KEY_ENV, AgentProvider
from .open_loops import OpenLoopsService

ICON_TITLE = "◔"
REFRESH_SECONDS = 60

PROVIDER_LABELS = {
    AgentProvider.CLAUDE_CLI.value: "Claude Code (no key)",
    AgentProvider.CODEX_CLI.value: "Codex (no key)",
    AgentProvider.ANTHROPIC.value: "Anthropic API",
    AgentProvider.OPENAI.value: "OpenAI API",
    AgentProvider.GEMINI.value: "Gemini API",
    AgentProvider.OLLAMA.value: "Ollama (local)",
}


class MementoBar(rumps.App):
    def __init__(self):
        super().__init__("Memento", title=ICON_TITLE, quit_button="Quit Memento")
        self.refresh(None)

    # ---- data helpers ----

    def _items_repo(self) -> ActionItemRepository:
        return ActionItemRepository(database.connect())

    def _open_items(self):
        return self._items_repo().open_items(limit=50)

    # ---- menu construction ----

    def refresh(self, _sender):
        cfg = load_config()
        items = self._open_items()
        self.menu.clear()

        header = rumps.MenuItem("{} open loop{}".format(
            len(items), "" if len(items) == 1 else "s"))  # no callback = disabled
        self.menu.add(header)
        self.menu.add(rumps.separator)

        if items:
            for it in items:
                self.menu.add(rumps.MenuItem("• " + it["title"],
                                             callback=self._make_done(it["id"])))
        else:
            self.menu.add(rumps.MenuItem("All clear \U0001F389"))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Review now", callback=self.review_now))
        paused = bool(cfg.get("paused"))
        self.menu.add(rumps.MenuItem("Resume capture" if paused else "Pause capture",
                                     callback=self.toggle_pause))
        self.menu.add(self._settings_menu(cfg))
        self.menu.add(rumps.MenuItem("Connect to Claude", callback=self.connect_claude))
        self.menu.add(rumps.separator)

    def _settings_menu(self, cfg) -> "rumps.MenuItem":
        provider = cfg.get("agent", {}).get("provider") or "none"
        settings = rumps.MenuItem("Settings")

        providers = rumps.MenuItem("AI Provider")
        for value, label in PROVIDER_LABELS.items():
            mi = rumps.MenuItem(label, callback=self._make_set_provider(value))
            mi.state = 1 if value == provider else 0
            providers.add(mi)
        settings.add(providers)

        settings.add(rumps.MenuItem("Set API key…", callback=self.set_api_key))
        settings.add(rumps.MenuItem("Set model…", callback=self.set_model))
        return settings

    # ---- actions ----

    def _make_done(self, item_id: int):
        def cb(_sender):
            self._items_repo().resolve(item_id, evidence="marked done from menu bar")
            self._notify("Closed", "Marked done")
            self.refresh(None)
        return cb

    def review_now(self, _sender):
        def work():
            cfg = load_config()
            conn = database.connect()
            try:
                r = OpenLoopsService(conn, cfg).run_once(window_minutes=240)
            finally:
                conn.close()
            self._notify("Review complete", "+{} new, {} closed".format(r["new"], r["resolved"]))
            self.refresh(None)
        threading.Thread(target=work, daemon=True).start()

    def toggle_pause(self, _sender):
        cfg = load_config()
        cfg["paused"] = not bool(cfg.get("paused"))
        save_config(cfg)
        self._notify("Capture " + ("paused" if cfg["paused"] else "resumed"), "")
        self.refresh(None)

    def _make_set_provider(self, provider: str):
        def cb(_sender):
            cfg = load_config()
            cfg["agent"]["provider"] = provider
            if provider in DEFAULT_KEY_ENV:
                cfg["agent"]["api_key_env"] = cfg["agent"].get("api_key_env") or DEFAULT_KEY_ENV[provider]
            save_config(cfg)
            self._notify("Provider set", PROVIDER_LABELS.get(provider, provider))
            # If it needs a key and none is stored, ask right away.
            if provider in DEFAULT_KEY_ENV and not cfg["agent"].get("api_key"):
                self.set_api_key(None)
            self.refresh(None)
        return cb

    def set_api_key(self, _sender):
        cfg = load_config()
        provider = cfg.get("agent", {}).get("provider") or "none"
        resp = rumps.Window(
            message="Paste your API key for {}".format(PROVIDER_LABELS.get(provider, provider)),
            title="Memento", default_text="", ok="Save", cancel="Cancel",
            dimensions=(360, 24)).run()
        if resp.clicked and resp.text.strip():
            cfg["agent"]["api_key"] = resp.text.strip()
            save_config(cfg)
            self._notify("Saved", "API key stored")
            self.refresh(None)

    def set_model(self, _sender):
        cfg = load_config()
        resp = rumps.Window(
            message="Model name (leave blank for the provider default)",
            title="Memento", default_text=cfg.get("agent", {}).get("model", ""),
            ok="Save", cancel="Cancel", dimensions=(300, 24)).run()
        if resp.clicked:
            cfg["agent"]["model"] = resp.text.strip()
            save_config(cfg)
            self.refresh(None)

    def connect_claude(self, _sender):
        cmd = "claude mcp add memento -- memento mcp"
        try:
            subprocess.run(["pbcopy"], input=cmd, text=True, timeout=5)
        except Exception:
            pass
        self._notify("Copied to clipboard", "Paste in a terminal to connect Claude")

    # ---- misc ----

    def _notify(self, title: str, message: str) -> None:
        try:
            rumps.notification("Memento", title, message)
        except Exception:
            pass

    @rumps.timer(REFRESH_SECONDS)
    def _tick(self, _sender):
        self.refresh(None)


def run() -> int:
    MementoBar().run()
    return 0
