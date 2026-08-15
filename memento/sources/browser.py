"""Active browser tab: URL + title via AppleScript.

Chromium browsers expose `active tab of front window`; WebKit (Safari/Orion)
use `current tab`. Firefox has no scripting dictionary for tabs, so it falls
back to the window title upstream.
"""

from __future__ import annotations

import subprocess
from typing import Optional, Tuple

from . import apps


def _osa(script: str, timeout: float = 5.0) -> Optional[str]:
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def active_tab(bundle: str, app_name: str) -> Optional[Tuple[str, str]]:
    """Return (url, title) for the frontmost tab, or None."""
    name = apps.BROWSERS.get(bundle) or apps.SAFARI_FAMILY.get(bundle) or app_name
    if apps.is_webkit(bundle):
        url = _osa('tell application "{}" to get URL of current tab of front window'.format(name))
        title = _osa('tell application "{}" to get name of current tab of front window'.format(name))
    else:
        url = _osa('tell application "{}" to get URL of active tab of front window'.format(name))
        title = _osa('tell application "{}" to get title of active tab of front window'.format(name))
    if not url:
        return None
    return url, (title or "")
