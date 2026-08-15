# Memento

**Local-first ambient memory for your Mac.** Memento runs quietly in the
background, captures what you're doing across your apps, and stores it locally.
Then it puts the assistant you already pay for — **Claude Code or Codex** — to
work *on* that memory: it **finds your open loops** (commitments and follow-ups)
and **closes them automatically** when your later activity shows they're done.

No cloud. No subscription. Your memory stays on your machine, and the AI work
runs through your existing `claude` / `codex` CLI — no API key required.

## What it does

1. **Finds your open loops.** The background agent reads your recent activity and
   surfaces the high-value action items you committed to but haven't closed.
2. **Closes them automatically.** It traces what you did next and resolves loops
   without you lifting a finger — recording the evidence for why each is done.

You can also just ask your assistant directly (*"what was I working on?"*) — the
memory is exposed over MCP too. But the point isn't querying; it's that Memento
*acts* on your behalf, continuously, in the background.

> Memento is an independent, clean-room, open-source project inspired by the
> *idea* of ambient memory apps. It is not affiliated with, and contains no code
> from, Minimi / SHRAM Insights.

---

## Why

Ambient memory is the useful, hard part: knowing what you were reading,
discussing, and deciding — without manually pasting context into a chat box. The
commercial versions do the AI in their cloud and charge a monthly fee. But if
you already pay for Claude Code or Codex, that LLM can do the reasoning for free
over a memory that lives entirely on your laptop. Memento is that memory.

It is **continuous and in the background** — not a "what's on my screen right
now" snapshot. The history is the whole point.

## How it works

```
                         your Mac (all local)
   ┌───────────────────────────────────────────────────────────┐
   │  capture daemon (LaunchAgent, runs at login)               │
   │     every N s: frontmost app + window title  ── privacy ─▶ │
   │                (excludes password managers, banking, …)    │
   │                              │                             │
   │                     dedup by fingerprint                   │
   │                              ▼                             │
   │            SQLite   threads → versions   (+ optional        │
   │                              │             embeddings)     │
   │                              ▼                             │
   │                        MCP server (stdio)                  │
   └──────────────────────────────┬────────────────────────────┘
                                   ▼
                    Claude Code / Codex / any MCP client
              search_memory · recent_context · list_threads · open_loops
```

- **threads** — one identity per app + window (the thing you were in).
- **versions** — deduped point-in-time snapshots, bucketed by hour.
- **search** — keyword by default (zero cost/keys); semantic if you enable embeddings.
- **open loops** — optional hourly agent extracts commitments/follow-ups.

## Install

Requires macOS + Python 3.9+.

```bash
git clone https://github.com/yourname/memento ~/code/memento
cd ~/code/memento
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

memento init      # create ~/.memento, the DB, and default config
```

Grant your terminal **Accessibility** permission (System Settings → Privacy &
Security → Accessibility) so window titles can be read. Then:

```bash
memento start     # background capture at login, 24x7
memento status    # see it filling up
```

A Homebrew formula template is in `packaging/memento.rb` for a `brew install`
flow once you publish a tap.

## Connect your assistant

Claude Code:

```bash
claude mcp add memento -- memento mcp
```

Or add to any MCP client's config:

```json
{
  "mcpServers": {
    "memento": { "command": "memento", "args": ["mcp"] }
  }
}
```

Then just ask: *"what was I working on before lunch?"*, *"find the thread where I
discussed the migration"*, *"what are my open loops?"*

## Commands

```
memento init | start | stop | restart | status | doctor
memento capture           # run the daemon in the foreground
memento mcp               # run the MCP server (what the assistant launches)
memento search "query"    # search from the terminal
memento recent --minutes 60
memento threads
memento loops
memento tail -n 50        # daemon log
```

## Configuration — `~/.memento/config.json`

```jsonc
{
  "capture_interval_seconds": 15,
  "exclude_apps": ["1Password", "Bitwarden", "Keychain Access", ...],
  "exclude_title_keywords": ["password", "login", "bank", "otp", ...],
  "capture_clipboard": false,
  "watchlist": ["invoice", "deadline"],   // notify when these appear
  "embeddings": { "provider": "none" },   // none | ollama | openai
  "agent":      { "provider": "none" }    // none | anthropic | openai | ollama
}
```

### Optional: semantic search (bring your own, or run it locally)

Free & local with [Ollama](https://ollama.com):

```bash
ollama pull nomic-embed-text
```
```jsonc
"embeddings": { "provider": "ollama", "model": "nomic-embed-text",
                "endpoint": "http://127.0.0.1:11434" }
```

Or with a key:

```jsonc
"embeddings": { "provider": "openai", "model": "text-embedding-3-small",
                "api_key_env": "OPENAI_API_KEY" }
```

### Optional: background "open loops" agent

```jsonc
"agent": { "provider": "anthropic", "model": "claude-sonnet-4-5",
           "api_key_env": "ANTHROPIC_API_KEY", "interval_seconds": 3600 }
```
(`openai` and local `ollama` are also supported.)

## Privacy

- Everything is local SQLite under `~/.memento`. Nothing is sent anywhere unless
  you explicitly turn on a cloud embeddings/agent provider — and even then only
  the text needed for that call goes to that provider.
- Password managers and sensitive-looking windows are excluded by default; add
  your own to `exclude_apps` / `exclude_title_keywords`.
- To wipe: `memento stop && rm -rf ~/.memento`.

## Roadmap

- Full Accessibility-tree text scrape (per-app parsers) beyond window titles.
- Encryption at rest (SQLCipher / field-level).
- Meeting/voice capture with local Whisper.
- Multi-scale open loops (days → months).

## License

MIT — see `LICENSE`.
