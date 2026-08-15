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

> Memento is an independent, open-source project.

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

Requires macOS. Uses [uv](https://docs.astral.sh/uv/) — no manual venv.

**One command:**

```bash
uv tool install git+https://github.com/yourname/memento && memento init && memento start
```

Or from a local checkout:

```bash
git clone https://github.com/yourname/memento ~/code/memento && cd ~/code/memento
./scripts/install.sh        # installs uv if needed, then installs + starts Memento
# or:  make install && memento init && memento start
```

Grant your terminal (or the installed tool) **Accessibility** permission —
System Settings → Privacy & Security → Accessibility — so window titles can be
read. Then `memento status` to watch it fill up.

**Homebrew** (once you publish a tap): a formula template lives in
`packaging/memento.rb`.

```bash
brew tap yourname/tap && brew install memento
memento init && memento start
```

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

## Menu-bar app

By default, `memento start` also launches a **menu-bar icon** (top-right of your
screen, left of Wi-Fi). Click it to see your open loops; click a loop to mark it
done; "Review now" runs the agent on demand.

```bash
memento menubar     # run just the menu-bar app in the foreground
```

It's installed as its own LaunchAgent so it reappears at login. Requires `rumps`
(a default dependency on macOS).

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

## Providers — use your CLI, or bring your own keys

By default `memento init` wires the agent to whichever CLI you already pay for
(`claude` or `codex`) — **no API key needed**. Switch any time with one command:

```bash
# use your Claude Code / Codex subscription (default, no key)
memento config agent --provider claude_cli
memento config agent --provider codex_cli

# OR bring your own key instead
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY= / GEMINI_API_KEY=
memento config agent --provider anthropic --model claude-sonnet-4-5
memento config agent --provider openai    --model gpt-4o-mini
memento config agent --provider gemini    --model gemini-2.0-flash

# OR run it fully local
memento config agent --provider ollama --model llama3.1
```

Optional semantic search (keyword search is the zero-cost default):

```bash
memento config embeddings --provider ollama --model nomic-embed-text     # local, free
memento config embeddings --provider openai --model text-embedding-3-small
memento config embeddings --provider gemini --model text-embedding-004
```

### Use it from ChatGPT / claude.ai / Gemini (custom connector)

Those clients take an MCP **link**, not a local command. Serve Memento over HTTP
and point the connector at it:

```bash
memento mcp --http --port 8787        # → http://127.0.0.1:8787/mcp
```

For a remote client, expose that port with a tunnel (e.g. `cloudflared tunnel`
/ `ngrok http 8787`) and paste the resulting HTTPS URL as a custom connector.

`memento config show` prints the current setup.

## Integrations — what gets captured

**Today (v0.1):** Memento captures the **frontmost app + window title** across
*every* app generically — WhatsApp, Gmail, Calendar, Slack, browsers, editors,
etc. all show up as threads and an activity timeline, and that alone is enough
for the open-loops agent to work. Optionally it can fold in the clipboard.

**Not yet:** deep *content* extraction per app (reading actual WhatsApp messages,
Gmail thread bodies, calendar event details). That requires per-app
Accessibility-tree parsers — the roadmap below. So: **broad coverage now,
shallow depth**; deep per-app integrations are the next milestone.

| App | Captured today | Deep content (planned) |
|-----|:--:|:--:|
| WhatsApp / Slack / Discord / Teams | title + activity | ⏳ AX parser |
| Gmail / Mail / Outlook | title + activity | ⏳ AX parser |
| Calendar / Fantastical | title + activity | ⏳ AX / AppleScript |
| Notion / Obsidian / Notes | title + activity | ⏳ AX parser |
| Browsers (any tab) | title (+ URL planned) | ⏳ AX parser |
| Everything else | title + activity | generic AX fallback |

The capture layer is built to be pluggable so these parsers can be added without
touching the store or agent.

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
