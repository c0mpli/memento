"""Frontmost window: app name, bundle id, and window title (osascript)."""

from __future__ import annotations

import subprocess
from typing import Dict, Optional

_SCRIPT = r'''
tell application "System Events"
    set p to first application process whose frontmost is true
    set nm to name of p
    set bid to ""
    try
        set bid to bundle identifier of p
    end try
    set wt to ""
    try
        set wt to name of front window of p
    end try
end tell
return nm & "\n" & bid & "\n" & wt
'''


def _osascript(script: str, timeout: float = 5.0) -> Optional[str]:
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out.stdout.rstrip("\n") if out.returncode == 0 else None


def frontmost() -> Optional[Dict[str, str]]:
    raw = _osascript(_SCRIPT)
    if raw is None:
        return None
    parts = (raw.split("\n") + ["", "", ""])[:3]
    app, bundle, title = (p.strip() for p in parts)
    if not app:
        return None
    return {"app": app, "bundle": bundle, "title": title}
