"""macOS capture: what app + window is in front right now.

This is the ambient sensor. The MVP reads the frontmost application and its
front window title via AppleScript (System Events) — no extra dependencies.
Optionally it folds in the clipboard.

Richer capture (full on-screen text via the Accessibility API, à la a real
AX-tree scrape) is the natural next step; `capture_once` is the single hook to
extend. To read window titles / AX you must grant the controlling terminal (or
the packaged app) Accessibility permission in System Settings → Privacy &
Security → Accessibility.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

# One AppleScript round-trip: frontmost process name + its front window title.
_FRONT_SCRIPT = r'''
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
    set winTitle to ""
    try
        tell (first application process whose frontmost is true)
            set winTitle to name of front window
        end tell
    end try
end tell
return frontApp & "\n" & winTitle
'''


def _osascript(script: str, timeout: float = 5.0) -> Optional[str]:
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.rstrip("\n")


def get_frontmost() -> Optional[Dict[str, str]]:
    raw = _osascript(_FRONT_SCRIPT)
    if raw is None:
        return None
    parts = raw.split("\n", 1)
    app = parts[0].strip() if parts else ""
    title = parts[1].strip() if len(parts) > 1 else ""
    if not app:
        return None
    return {"app": app, "title": title}


def get_clipboard() -> str:
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3.0)
        return out.stdout if out.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _is_excluded(app: str, title: str, cfg: Dict[str, Any]) -> bool:
    if app in cfg.get("exclude_apps", []):
        return True
    hay = ("{} {}".format(app, title)).lower()
    for kw in cfg.get("exclude_title_keywords", []):
        if kw and kw.lower() in hay:
            return True
    return False


def capture_once(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Return {"app","title","content"} for the current front window, or None
    if nothing capturable / excluded by privacy rules."""
    front = get_frontmost()
    if front is None:
        return None
    app, title = front["app"], front["title"]
    if _is_excluded(app, title, cfg):
        return None

    content = title
    if cfg.get("capture_clipboard"):
        clip = get_clipboard().strip()
        if clip and len(clip) <= 4000:
            content = (title + "\n" + clip).strip() if title else clip

    if not content:
        content = "(no window title)"
    return {"app": app, "title": title, "content": content}
