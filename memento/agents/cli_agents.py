"""CLI-backed agents: reuse the `claude` / `codex` you already pay for.

No API key — these shell out to the CLI's own authenticated session. The argv
is overridable via config `agent.command` ("{prompt}" is substituted; if absent
the prompt is fed on stdin).
"""

from __future__ import annotations

import subprocess
from typing import List

from .base import LLMAgent


class CliAgent(LLMAgent):
    default_argv: List[str] = []

    def complete(self, prompt: str) -> str:
        argv = self.cfg.get("command") or self.default_argv
        if any("{prompt}" in a for a in argv):
            argv = [a.replace("{prompt}", prompt) for a in argv]
            stdin = None
        else:
            stdin = prompt
        try:
            out = subprocess.run(argv, input=stdin, capture_output=True,
                                 text=True, timeout=180)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""
        return out.stdout if out.returncode == 0 else ""


class ClaudeCliAgent(CliAgent):
    default_argv = ["claude", "-p", "{prompt}"]


class CodexCliAgent(CliAgent):
    default_argv = ["codex", "exec", "{prompt}"]
