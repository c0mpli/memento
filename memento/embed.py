"""Optional embeddings for semantic search.

Providers (configured in ~/.memento/config.json under "embeddings"):
    none    disabled — Memento uses keyword search (default, zero cost/keys)
    ollama  local & free; run `ollama pull nomic-embed-text` first
    openai  set model "text-embedding-3-small" + api_key_env "OPENAI_API_KEY"

Uses only the stdlib (urllib) so there is no dependency to install for the core.
Returns None on any failure so the daemon degrades gracefully to keyword search.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional


def embed_text(cfg: Dict[str, Any], text: str) -> Optional[List[float]]:
    ec = cfg.get("embeddings", {})
    provider = (ec.get("provider") or "none").lower()
    text = (text or "").strip()
    if not text or provider == "none":
        return None
    try:
        if provider == "ollama":
            return _ollama(ec, text)
        if provider == "openai":
            return _openai(ec, text)
    except Exception:
        return None
    return None


def _post(url: str, payload: Dict[str, Any],
          headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama(ec: Dict[str, Any], text: str) -> Optional[List[float]]:
    endpoint = ec.get("endpoint") or "http://127.0.0.1:11434"
    model = ec.get("model") or "nomic-embed-text"
    out = _post(endpoint.rstrip("/") + "/api/embeddings", {"model": model, "prompt": text})
    vec = out.get("embedding")
    return [float(x) for x in vec] if vec else None


def _openai(ec: Dict[str, Any], text: str) -> Optional[List[float]]:
    key = os.environ.get(ec.get("api_key_env") or "OPENAI_API_KEY", "")
    if not key:
        return None
    model = ec.get("model") or "text-embedding-3-small"
    out = _post(
        "https://api.openai.com/v1/embeddings",
        {"model": model, "input": text},
        headers={"Authorization": "Bearer " + key},
    )
    data = out.get("data") or []
    return [float(x) for x in data[0]["embedding"]] if data else None
