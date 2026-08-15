"""Capture sources — turn "the frontmost window" into a memory row.

Orchestration: pick the richest available source for the focused app.
  browser  → active tab URL + title (Chrome/Safari/Arc/Brave/Edge/…)
  ax_text  → focused-window Accessibility text (daily work apps, if pyobjc present)
  window   → app + window title (always available fallback)

Adding an app is data-only (see `apps.py`); nothing else changes.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

from . import apps, ax_text, browser, window

MAX_CONTENT = 4000


def _pbpaste() -> str:
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
        return out.stdout if out.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _excluded(app: str, title: str, cfg: Dict[str, Any]) -> bool:
    if app in cfg.get("exclude_apps", []):
        return True
    hay = "{} {}".format(app, title).lower()
    return any(kw and kw.lower() in hay for kw in cfg.get("exclude_title_keywords", []))


def capture_once(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Return {"app","title","content"} for the focused window, or None if
    nothing capturable / excluded by privacy rules."""
    front = window.frontmost()
    if front is None:
        return None
    app, bundle, title = front["app"], front["bundle"], front["title"]
    if _excluded(app, title, cfg):
        return None

    content = title
    if apps.is_browser(bundle):
        tab = browser.active_tab(bundle, app)
        if tab:
            url, tab_title = tab
            # re-check against the actual page (private/banking sites, etc.)
            if _excluded(app, "{} {}".format(tab_title, url), cfg):
                return None
            title = tab_title or title
            content = "{}\n{}".format(tab_title, url) if tab_title else url
    elif ax_text.available() and apps.is_work_app(bundle):
        text = ax_text.extract(bundle, app)
        if text:
            content = "{}\n{}".format(title, text) if title else text

    if cfg.get("capture_clipboard"):
        clip = _pbpaste().strip()
        if clip and len(clip) <= 2000:
            content = (content + "\n" + clip).strip()

    content = (content or "(no window title)")[:MAX_CONTENT]
    return {"app": app, "title": title, "content": content}
