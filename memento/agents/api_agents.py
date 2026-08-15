"""API-key-backed agents: Anthropic, OpenAI, Gemini, Ollama.

Each reads its key from the env var named in config `agent.api_key_env`
(sensible default per provider) and returns "" if unavailable, so the caller
degrades gracefully. stdlib-only HTTP.
"""

from __future__ import annotations

import os

from .base import LLMAgent, http_post_json


class AnthropicAgent(LLMAgent):
    def complete(self, prompt: str) -> str:
        key = os.environ.get(self.cfg.get("api_key_env") or "ANTHROPIC_API_KEY", "")
        if not key:
            return ""
        out = http_post_json(
            "https://api.anthropic.com/v1/messages",
            {"model": self.cfg.get("model") or "claude-sonnet-4-5", "max_tokens": 1024,
             "messages": [{"role": "user", "content": prompt}]},
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        return "".join(b.get("text", "") for b in out.get("content", []))


class OpenAIAgent(LLMAgent):
    def complete(self, prompt: str) -> str:
        key = os.environ.get(self.cfg.get("api_key_env") or "OPENAI_API_KEY", "")
        if not key:
            return ""
        out = http_post_json(
            "https://api.openai.com/v1/chat/completions",
            {"model": self.cfg.get("model") or "gpt-4o-mini",
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": "Bearer " + key},
        )
        return out["choices"][0]["message"]["content"]


class GeminiAgent(LLMAgent):
    def complete(self, prompt: str) -> str:
        key = (os.environ.get(self.cfg.get("api_key_env") or "GEMINI_API_KEY", "")
               or os.environ.get("GOOGLE_API_KEY", ""))
        if not key:
            return ""
        model = self.cfg.get("model") or "gemini-2.0-flash"
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               "{}:generateContent?key={}".format(model, key))
        out = http_post_json(url, {"contents": [{"parts": [{"text": prompt}]}]})
        text = ""
        for cand in out.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return text


class OllamaAgent(LLMAgent):
    def complete(self, prompt: str) -> str:
        endpoint = (self.cfg.get("endpoint") or "http://127.0.0.1:11434").rstrip("/")
        out = http_post_json(
            endpoint + "/api/chat",
            {"model": self.cfg.get("model") or "llama3.1", "stream": False,
             "messages": [{"role": "user", "content": prompt}]},
        )
        return out.get("message", {}).get("content", "")
