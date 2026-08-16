"""Agent base class + shared helpers.

An "agent" here is a thin client over one LLM provider. It knows only how to
turn a prompt into text — no prompts (those live in `config.prompts`) and no
database access (that's the `repository` layer).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

_RETRY_CODES = {429, 500, 502, 503, 504}


class LLMAgent(ABC):
    """One provider. `complete(prompt) -> text`."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def api_key(self, *env_vars: str) -> str:
        """Resolve the key: an in-app-saved `api_key` wins, else the env var
        named in `api_key_env`, else the provider's default env var(s)."""
        if self.cfg.get("api_key"):
            return str(self.cfg["api_key"])
        candidates: List[str] = []
        if self.cfg.get("api_key_env"):
            candidates.append(self.cfg["api_key_env"])
        candidates.extend(env_vars)
        for name in candidates:
            if os.environ.get(name):
                return os.environ[name]
        return ""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        ...


def http_post_json(url: str, payload: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None,
                   timeout: float = 60.0, retries: int = 5) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_CODES and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise
    return {}


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


def parse_json_array(text: str) -> list:
    """Extract the outermost JSON array from a model response."""
    text = (text or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return []
