"""macOS menu-bar app: a top-bar icon that drops down your open loops.

Click the icon to see open loops; click a loop to mark it done; "Review now"
runs the agent on demand. Built on `rumps` (optional extra):

    pip install "memento-memory[menubar]"     # or: uv sync --extra menubar
    memento menubar

Runs in your GUI session (add it to Login Items to have it always present).
"""

from __future__ import annotations

import threading

try:
    import rumps
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "The 'rumps' package is required for the menu bar.\n"
        "Install it:  pip install 'memento-memory[menubar]'   (or: uv sync --extra menubar)\n"
        "(original error: {})".format(exc)
    )

from ..config import load_config
from ..core import database
from ..repository import ActionItemRepository
from .open_loops import OpenLoopsService

ICON_TITLE = "◔"  # ◔  — small, unobtrusive glyph in the status bar
REFRESH_SECONDS = 60


class MementoBar(rumps.App):
    def __init__(self):
        super().__init__("Memento", title=ICON_TITLE, quit_button="Quit Memento")
        self.refresh(None)

    # ---- data ----

    def _open_items(self):
        conn = database.connect()
        try:
            return ActionItemRepository(conn).open_items(limit=50)
        finally:
            conn.close()

    def _resolve(self, item_id: int):
        conn = database.connect()
        try:
            ActionItemRepository(conn).resolve(item_id, evidence="marked done from menu bar")
        finally:
            conn.close()

    # ---- menu ----

    def refresh(self, _sender):
        items = self._open_items()
        menu = []
        header = rumps.MenuItem("{} open loop{}".format(
            len(items), "" if len(items) == 1 else "s"))  # no callback -> disabled header
        menu.append(header)
        menu.append(None)
        if items:
            for it in items:
                menu.append(rumps.MenuItem("• " + it["title"],
                                           callback=self._make_done(it["id"])))
        else:
            menu.append(rumps.MenuItem("All clear \U0001F389"))  # disabled
        menu.append(None)
        menu.append(rumps.MenuItem("Review now", callback=self.review_now))
        menu.append(rumps.MenuItem("Refresh", callback=self.refresh))
        self.menu.clear()
        self.menu.update(menu)

    def _make_done(self, item_id: int):
        def cb(_sender):
            self._resolve(item_id)
            try:
                rumps.notification("Memento", "Closed", "Marked done")
            except Exception:
                pass
            self.refresh(None)
        return cb

    def review_now(self, _sender):
        def work():
            cfg = load_config()
            conn = database.connect()
            try:
                OpenLoopsService(conn, cfg).run_once()
            finally:
                conn.close()
            self.refresh(None)
        threading.Thread(target=work, daemon=True).start()

    @rumps.timer(REFRESH_SECONDS)
    def _tick(self, _sender):
        self.refresh(None)


def run() -> int:
    MementoBar().run()
    return 0
