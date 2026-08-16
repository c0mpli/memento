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
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

_RETRY_CODES = {429, 500, 502, 503, 504}


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
        if provider == "gemini":
            return _gemini(ec, text)
    except Exception:
        return None
    return None


def embed_texts(cfg: Dict[str, Any], texts: List[str]) -> List[Optional[List[float]]]:
    """Batch-embed many texts. Uses the provider's batch API where possible
    (OpenAI accepts an array), else falls back to per-item calls."""
    ec = cfg.get("embeddings", {})
    provider = (ec.get("provider") or "none").lower()
    if not texts or provider == "none":
        return [None] * len(texts)
    if provider == "openai":
        try:
            return _openai_batch(ec, texts)
        except Exception:
            pass
    return [embed_text(cfg, t) for t in texts]


def _openai_batch(ec: Dict[str, Any], texts: List[str],
                  chunk: int = 256) -> List[Optional[List[float]]]:
    key = os.environ.get(ec.get("api_key_env") or "OPENAI_API_KEY", "")
    if not key:
        return [None] * len(texts)
    model = ec.get("model") or "text-embedding-3-small"
    out: List[Optional[List[float]]] = []
    for i in range(0, len(texts), chunk):
        batch = [(t or " ").strip() or " " for t in texts[i:i + chunk]]
        resp = _post("https://api.openai.com/v1/embeddings",
                     {"model": model, "input": batch},
                     {"Authorization": "Bearer " + key}, timeout=60.0)
        data = sorted(resp.get("data") or [], key=lambda d: d["index"])
        vecs = [[float(x) for x in d["embedding"]] for d in data]
        if len(vecs) != len(batch):
            vecs += [None] * (len(batch) - len(vecs))
        out.extend(vecs)
    return out


def _post(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None,
          timeout: float = 30.0, retries: int = 5) -> Dict[str, Any]:
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


def _gemini(ec: Dict[str, Any], text: str) -> Optional[List[float]]:
    key = (os.environ.get(ec.get("api_key_env") or "GEMINI_API_KEY", "")
           or os.environ.get("GOOGLE_API_KEY", ""))
    if not key:
        return None
    model = ec.get("model") or "text-embedding-004"
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{}:embedContent?key={}".format(model, key))
    out = _post(url, {"model": "models/" + model,
                      "content": {"parts": [{"text": text}]}})
    values = (out.get("embedding") or {}).get("values")
    return [float(x) for x in values] if values else None
