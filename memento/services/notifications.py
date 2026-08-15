"""macOS notifications via osascript (no dependencies)."""

from __future__ import annotations

import subprocess


def notify(title: str, message: str) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = 'display notification "{}" with title "{}"'.format(
        esc(message[:240]), esc(title[:120])
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5.0)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
