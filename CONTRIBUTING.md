# Contributing / Developer guide

Everything technical about Memento: how it's built, how to run it, and how to
extend it. (The [README](README.md) is the product pitch.)

Memento is a local-first macOS menu-bar app. It captures your activity, stores it
in a local SQLite DB, finds "open loops" with an LLM you already pay for, and
auto-closes them — plus an MCP surface so any assistant can query your memory.

---

## Requirements

- macOS
- Python 3.9+
- [uv](https://docs.astral.sh/uv/)
- Accessibility permission for the process that runs capture (System Settings →
  Privacy & Security → Accessibility)

## Run from source

```bash
git clone https://github.com/c0mpli/memento ~/code/memento && cd ~/code/memento
uv sync                       # create the venv + install deps
uv run memento init           # ~/.memento (db + config)
uv run memento capture        # run the daemon in the foreground (Ctrl-C to stop)
uv run memento menubar        # run the menu-bar app in the foreground
# or just:
python main.py init && python main.py capture
```

`memento` (no args) = `init` + `start` (loads the LaunchAgents; the icon appears).

## Architecture

Layered, one concern per package:

```
memento/
  main.py / __main__.py     entrypoints (python main.py … / python -m memento …)
  cli.py                    argparse CLI; bare `memento` bootstraps everything
  types.py                  str-enums: providers, item status, transport, events
  core/                     infrastructure
    database.py             connection + schema + bootstrap (only place schema lives)
    logger.py               structured logging  ->  CODE_AREA_STATUS ,{json}
  config/
    settings.py             paths + DEFAULTS + load/save
    prompts.py              ALL LLM prompts
  repository/               the ONLY code that runs SQL
    memory.py               MemoryRepository (threads/versions/embeddings)
    action_items.py         ActionItemRepository (open loops)
  agents/                   LLM provider factory
    base.py                 LLMAgent ABC + http + json helpers
    cli_agents.py           ClaudeCliAgent, CodexCliAgent (reuse your CLI, no key)
    api_agents.py           Anthropic/OpenAI/Gemini/Ollama
    __init__.py             create_agent(cfg) -> LLMAgent
  sources/                  capture sources (how a window becomes a memory row)
    window.py               frontmost app + bundle + title
    browser.py              active tab URL + title (AppleScript)
    ax_text.py              focused-window Accessibility text (pyobjc, optional)
    apps.py                 known browsers + daily work-app registry
    __init__.py             capture_once(cfg) orchestrator
  services/                 application logic
    daemon.py               the background loop (capture + periodic agent)
    open_loops.py           find + auto-close loops (orchestrates agent+repo+prompts)
    embeddings.py           optional semantic-search vectors
    notifications.py        macOS notifications
    menubar.py              the menu-bar UI (rumps)
  mcp/
    server.py               MCP server (stdio + streamable-HTTP)
```

Rules of the layering:
- **Only `repository/` issues SQL.** `core/database.py` owns the schema/engine.
- **All prompts live in `config/prompts.py`.**
- **Adding an app is data-only** — edit `sources/apps.py`.

## Data model

`threads` → `versions` → (open) `action_items`.

- **thread**: one identity per app + window title (the thing you were in)
- **version**: a deduped point-in-time snapshot (fingerprint = sha256 of
  identity + normalized content), bucketed by hour
- **action_item**: an open loop; `status` open|resolved with `resolution_evidence`

## CLI reference

```
memento                     # bootstrap: init + start (icon appears)
memento init                # create ~/.memento
memento start | stop | restart
memento status | doctor | tail -n 50
memento capture             # foreground daemon (used by the LaunchAgent)
memento menubar             # foreground menu-bar app
memento review [--minutes N]# run the agent once now
memento mcp [--http --host --port]
memento search "query" [--limit]
memento recent [--minutes] [--limit]
memento threads [--limit]
memento loops [--all]
memento config show
memento config agent --provider <p> [--model --key-env --command --interval]
memento config embeddings --provider <p> [--model --key-env --endpoint]
```

All output is structured: `CODE_AREA_STATUS ,{json}`.

## Providers (agent)

Set from the menu bar, or:

```bash
memento config agent --provider claude_cli      # default, no key
memento config agent --provider codex_cli
memento config agent --provider anthropic --model claude-sonnet-4-5   # ANTHROPIC_API_KEY
memento config agent --provider openai    --model gpt-4o-mini         # OPENAI_API_KEY
memento config agent --provider gemini    --model gemini-2.0-flash    # GEMINI_API_KEY
memento config agent --provider ollama    --model llama3.1            # local
```

Keys resolve as: `agent.api_key` saved in config (what the menu bar writes) →
the env var named in `agent.api_key_env` → the provider default. New provider
classes: add to `agents/`, register in `agents/__init__.py::_REGISTRY`.

## Embeddings (optional semantic search)

Keyword search is the zero-cost default. For semantic:

```bash
memento config embeddings --provider ollama --model nomic-embed-text     # local, free
memento config embeddings --provider openai --model text-embedding-3-small
memento config embeddings --provider gemini --model text-embedding-004
```

## Capture — supported apps

`capture_once()` picks the richest source per focused app:

| Source | Apps | What it captures |
|--------|------|------------------|
| browser | Chrome, Safari, Arc, Brave, Edge, Vivaldi, Zen, Comet, Opera, Orion | active tab **URL + title** |
| ax_text (needs `[ax]`) | Slack, Teams, Discord, WhatsApp, Telegram, Mail, Outlook, Spark, Notion, Obsidian, Notes, Word, Pages, Linear, Things, Todoist, OmniFocus, VS Code, Cursor, Terminal, iTerm, Zoom | focused-window **text** |
| window | everything else | app + **window title** |

Deep Accessibility text needs pyobjc:

```bash
uv sync --extra ax        # or: pip install "memento-memory[ax]"
```

Add an app: put its bundle id in `sources/apps.py` (`BROWSERS`, `SAFARI_FAMILY`,
or `WORK_APPS`). For app-specific parsing, extend `sources/ax_text.py`.

Privacy: password managers and sensitive-looking titles are excluded by default
(`exclude_apps`, `exclude_title_keywords` in config); browser tabs are re-checked
against the page title + URL before capture.

## MCP

```bash
claude mcp add memento -- memento mcp        # stdio, for Claude Code / Codex
memento mcp --http --port 8787               # streamable-HTTP for custom connectors
```

Tools: `search_memory`, `recent_context`, `list_threads`, `get_thread`,
`open_loops`. For ChatGPT/claude.ai/Gemini, expose the HTTP port with a tunnel
and paste the URL as a custom connector.

## Config file — `~/.memento/config.json`

```jsonc
{
  "capture_interval_seconds": 15,
  "paused": false,
  "exclude_apps": ["1Password", "Bitwarden", "Keychain Access"],
  "exclude_title_keywords": ["password", "login", "bank", "otp"],
  "capture_clipboard": false,
  "watchlist": ["invoice", "deadline"],
  "embeddings": { "provider": "none" },
  "agent": { "provider": "claude_cli", "interval_seconds": 3600 }
}
```

Config is re-read every tick, so menu-bar changes (provider, key, pause) apply
live without restarting the daemon.

## Publishing to Homebrew

1. Tag a release: `git tag v0.1.0 && git push --tags`.
2. In your tap repo (`c0mpli/homebrew-tap`), add `Formula/memento.rb` (start from
   `packaging/memento.rb`), set `url` to the release tarball + its `sha256`, and
   run `brew update-python-resources` to vendor `mcp` / `rumps`.
3. `brew tap c0mpli/tap && brew install memento`.

## Accuracy / eval

`memento eval` scores retrieval + QA accuracy per question type, the same six
categories the memory benchmarks (LongMemEval) report.

```bash
memento eval                       # bundled 6-case smoke sample (one per type)
memento eval --dataset longmemeval_s.json --top-k 10
memento config embeddings --provider gemini --model text-embedding-004   # fairer retrieval
```

Each case is ingested into a fresh in-memory DB, retrieved with Memento's own
search, answered by the configured agent, and graded by the same agent as an LLM
judge, so the score reflects the real end-to-end product. The bundled sample has
no distractor sessions (it's a smoke test); download LongMemEval-S for a real
number and pass `--dataset`. Retrieval quality is the main lever, so turn on
embeddings for a fair comparison against embedding-based systems.

Code: `memento/eval/` (dataset loader, per-case harness, metrics); prompts in
`config/prompts.py`.

## Roadmap

- Richer per-app AX parsers (message-level, not just visible text)
- Encryption at rest (SQLCipher / field-level)
- Meeting/voice capture with local Whisper
- Multi-scale open loops (days → months)
- Full LongMemEval-S run + published per-category numbers
