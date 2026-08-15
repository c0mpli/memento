"""Agent factory — map an AgentProvider to its client.

    agent = create_agent(cfg["agent"])
    text  = agent.complete(prompt) if agent else ""
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from ..types import AgentProvider
from .api_agents import AnthropicAgent, GeminiAgent, OllamaAgent, OpenAIAgent
from .base import LLMAgent, parse_json_object
from .cli_agents import ClaudeCliAgent, CodexCliAgent

_REGISTRY: Dict[AgentProvider, Type[LLMAgent]] = {
    AgentProvider.CLAUDE_CLI: ClaudeCliAgent,
    AgentProvider.CODEX_CLI: CodexCliAgent,
    AgentProvider.ANTHROPIC: AnthropicAgent,
    AgentProvider.OPENAI: OpenAIAgent,
    AgentProvider.GEMINI: GeminiAgent,
    AgentProvider.OLLAMA: OllamaAgent,
}


def create_agent(agent_cfg: Dict[str, Any]) -> Optional[LLMAgent]:
    """Build the configured agent, or None if the provider is 'none'/unknown."""
    try:
        provider = AgentProvider(agent_cfg.get("provider") or "none")
    except ValueError:
        return None
    cls = _REGISTRY.get(provider)
    return cls(agent_cfg) if cls else None


__all__ = ["create_agent", "LLMAgent", "parse_json_object"]
