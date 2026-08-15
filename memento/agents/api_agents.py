"""API-key-backed agents: Anthropic, OpenAI, Gemini, Ollama.

The key comes from `api_key` saved in config (entered in the menu bar) or the
env var in `api_key_env` — see LLMAgent.api_key(). Returns "" when unavailable
so the caller degrades gracefully. stdlib-only HTTP.
"""

from __future__ import annotations

from .base import LLMAgent, http_post_json


class AnthropicAgent(LLMAgent):
    def complete(self, prompt: str) -> str:
        key = self.api_key("ANTHROPIC_API_KEY")
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
        key = self.api_key("OPENAI_API_KEY")
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
        key = self.api_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
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
