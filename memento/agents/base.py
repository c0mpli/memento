"""Agent base class + shared helpers.

An "agent" here is a thin client over one LLM provider. It knows only how to
turn a prompt into text — no prompts (those live in `config.prompts`) and no
database access (that's the `repository` layer).
"""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class LLMAgent(ABC):
    """One provider. `complete(prompt) -> text`."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    @abstractmethod
    def complete(self, prompt: str) -> str:
        ...


def http_post_json(url: str, payload: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None,
                   timeout: float = 60.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_json_object(text: str) -> Dict[str, Any]:
    """Extract the outermost JSON object from a model response."""
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}
