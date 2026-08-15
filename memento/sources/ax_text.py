"""Accessibility-tree text extraction for native apps (optional).

Reads visible text from the focused window's AX tree via pyobjc. Best-effort and
fully guarded: any failure returns None and the caller falls back to the title.

Enable with the `ax` extra:  pip install "memento-memory[ax]"
Requires Accessibility permission for the running process.
"""

from __future__ import annotations

from typing import List, Optional

try:
    from AppKit import NSWorkspace
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
    )
    _AVAILABLE = True
except Exception:  # pyobjc not installed
    _AVAILABLE = False

_CHILDREN = "AXChildren"
_FOCUSED_WINDOW = "AXFocusedWindow"
_TEXT_ATTRS = ("AXValue", "AXTitle", "AXDescription")

MAX_NODES = 3000
MAX_DEPTH = 60
MAX_CHARS = 4000


def available() -> bool:
    return _AVAILABLE


def _copy(el, attr):
    try:
        err, val = AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None
    except Exception:
        return None


def extract(bundle: str = "", app: str = "") -> Optional[str]:
    if not _AVAILABLE:
        return None
    try:
        fa = NSWorkspace.sharedWorkspace().frontmostApplication()
        if fa is None:
            return None
        root = AXUIElementCreateApplication(fa.processIdentifier())
        window = _copy(root, _FOCUSED_WINDOW) or root

        texts: List[str] = []
        state = {"nodes": 0, "chars": 0}

        def walk(el, depth: int) -> None:
            if (depth > MAX_DEPTH or state["nodes"] > MAX_NODES
                    or state["chars"] > MAX_CHARS):
                return
            state["nodes"] += 1
            for attr in _TEXT_ATTRS:
                v = _copy(el, attr)
                if isinstance(v, str):
                    s = v.strip()
                    if len(s) > 1:
                        texts.append(s)
                        state["chars"] += len(s)
            children = _copy(el, _CHILDREN)
            if children:
                try:
                    kids = list(children)
                except Exception:
                    kids = []
                for c in kids:
                    walk(c, depth + 1)

        walk(window, 0)

        seen = set()
        deduped = []
        for t in texts:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        joined = " • ".join(deduped)
        return joined[:MAX_CHARS] or None
    except Exception:
        return None
