# TurnZero

**Persistent context memory for AI sessions — built for developers, DevOps, and security engineers.**

Every AI session starts cold. The model doesn't know your stack's quirks, your infra constraints, or the corrections you've already made a hundred times. TurnZero loads that context before Turn 0 — your personal standards, your project-specific rules, and domain knowledge relevant to the task — so you stop re-establishing the same ground every session.

Built for people who live in the terminal and work across many stacks: backend engineers, DevOps and SRE, security engineers, platform and infra teams. If you use AI coding assistants daily and repeatedly correct the same mistakes, TurnZero is for you.

It doesn't eliminate mistakes — AI is still non-deterministic and won't follow injected priors 100% of the time. The goal is to nudge the model toward your preferred behavior from the start, reducing corrections mid-session.

Raw prompt text is never stored. Injection is always client-side.

---

[![Demo](https://asciinema.org/a/8IV2yoLNTloSlZo0.svg)](https://asciinema.org/a/8IV2yoLNTloSlZo0)

---

## How it works

Two types of priors inject at session start:

**Personal Priors (always-on):** Your preferences and standards — response style, coding conventions, workflow rules — loaded once per session. These follow you across every supported AI client. When you switch from Claude Code to Cursor to Gemini CLI, the same preferences are there.

**Expert Priors (semantic):** Domain-specific knowledge and stack-specific gotchas retrieved via embedding similarity to your opening prompt. The AI sees `expire_on_commit=False` is required with async SQLAlchemy, or that `@app.on_event` is deprecated in FastAPI 0.93+, before it has a chance to get it wrong.

Both types are constraints, not guarantees. The AI is more likely to follow them, not certain to.

### Session model

- **Turn 0:** Personal Priors inject once. Expert Priors matching the opening prompt inject alongside them.
- **Follow-up turns:** TurnZero checks for newly relevant Expert Priors only — no re-injection of priors already used.
- **New session or reset:** Personal Priors become eligible again.

### Private by design

Personal Priors live in a dedicated local-only tier. They are never synced or shared. The `community` tier (Expert Priors) is separate.

---

## Install

```bash
pipx install turnzero
turnzero setup
```

Python support: `3.12`, `3.13`, and `3.14`.

`turnzero setup` registers the TurnZero MCP server with Claude Code, Cursor, Claude Desktop, and Gemini CLI. It builds the embedding index and confirms your embedding backend is working.

**Embedding backend — pick one:**

| Option | Setup |
|---|---|
| ollama (local, free, private) | `ollama serve && ollama pull nomic-embed-text` |
| OpenAI API | `export OPENAI_API_KEY=sk-...` |

With `ollama`, embeddings never leave your machine. With OpenAI, the prompt text is sent to OpenAI's embedding API for that request and not stored by TurnZero.

---

## IDE Integration

### Claude Code

```bash
turnzero setup
```

MCP server is registered globally. Open a new session — Personal Priors apply once at session start, Expert Priors add when relevant.

```bash
# Optional: install the UserPromptSubmit hook for guaranteed injection
# regardless of model behaviour
turnzero setup --with-hook
```

### Claude Code (manual)

```bash
claude mcp add turnzero /path/to/.venv/bin/turnzero-mcp --scope user
```

### Cursor

See [`docs/cursor-setup.md`](docs/cursor-setup.md).

### Gemini CLI

```bash
turnzero setup
```

MCP server registered in `~/.gemini/settings.json`, rules added to `~/.gemini/GEMINI.md`.

### Any other MCP-compatible client

Register the MCP server via that client's config. The server's `instructions` field tells the AI when and how to call `list_suggested_blocks`.

---

## Verify it works

```bash
turnzero verify
```

Runs a full diagnostic: embedding backend, index health, client registrations, and a live retrieval probe. If anything is misconfigured, it tells you what to fix.

```bash
turnzero preview "Building a FastAPI REST API with Pydantic models and async SQLAlchemy"
```

Shows what Personal Priors and Expert Priors would inject for that prompt.

---

## How the library grows

When the AI gets something wrong and you correct it mid-session, TurnZero can capture that correction as a new Expert Prior via `submit_candidate`. Next time you open a session on the same stack, the prior is already there.

```
"No, use asyncpg not psycopg2 — psycopg2 blocks the event loop"
              │
              ▼
    AI calls submit_candidate with the correction
              │
              ▼
    Block written locally, index rebuilt
              │
              ▼
    Injected in future sessions matching that stack
```

AI-submitted blocks start with lower confidence and can be reviewed with `turnzero review`. The flywheel is probabilistic — a prior being present doesn't mean the AI will always follow it, but it improves the odds, and the library compounds over time.

---

## CLI

```bash
turnzero setup                                             # register MCP, build index
turnzero verify                                            # full system diagnostic
turnzero preview "build a Next.js 15 app with Supabase"   # preview what would inject
turnzero query   "build a Next.js 15 app with Supabase"   # ranked block list
turnzero inject  nextjs15-approuter-build                  # formatted output for one or more block slugs
turnzero show    nextjs15-approuter-build                  # full block content
turnzero stats                                             # library + session stats
turnzero review                                            # review pending candidates + low-confidence blocks
```

For non-MCP clients, manual fallback:

```bash
turnzero query   "build a Next.js 15 app with Supabase"   # find candidate slugs
turnzero show    nextjs15-approuter-build                  # inspect one block
turnzero inject  nextjs15-approuter-build                  # print formatted prior text to paste manually
```

---

## Expert Prior schema

```yaml
slug: nextjs15-approuter-build    # kebab-case, version-anchored
domain: nextjs
intent: build                    # build | debug | migrate | review
last_verified: "2026-04-19"
verification_level: curated      # curated | observed | synthetic
tags: [nextjs, react, approuter]
context_weight: 900              # estimated tokens when injected
confidence: 1.0                  # 0.0-1.0; AI-submitted blocks start lower
archived: false                  # set to true to exclude from retrieval
constraints:
  - "Use App Router (app/) — all new projects default to App Router in Next.js 13+"
  - "fetch() in Next.js 15 is not cached by default — add { cache: 'force-cache' } explicitly"
anti_patterns:
  - "Do not use getServerSideProps — Pages Router only, does not exist in App Router"
  - "Do not use next/router — use next/navigation in App Router"
doc_anchors:
  - url: "https://nextjs.org/docs/app/building-your-application/rendering/server-components"
    verified: "2026-04-19"
```

---

## Knowledge domains

143 Expert Priors across 37 domains — web frameworks, databases, cloud infra, security, CI/CD, containerisation, and more. Coverage is deepest where corrections come from real sessions: FastAPI, Next.js, PostgreSQL, Docker, Kubernetes, Redis, Supabase, Django, Rails, and others. The library grows from your sessions via `submit_candidate`.

---

## What makes a good Expert Prior

**The test:** *Would a stranger on the same stack, facing the same problem, be better off knowing this before Turn 0?*

| Good | Bad |
|---|---|
| `Do not use getServerSideProps in App Router` — removed in Next.js 13 | "Use PyCharm" — personal preference |
| `expire_on_commit=False required with AsyncSession` — raises MissingGreenlet without it | "Don't commit API keys" — generic noise |
| `Supabase RLS is off by default on new tables` — silently breaks auth | "Use Docker Compose for local dev" — workflow choice |
| `K8s readiness probe failure removes pod from LB but does not restart it` — use liveness for restarts | "Be more concise" — personal style preference |
| `SSRF validation must block 169.254.169.254` — AWS metadata endpoint, most WAFs miss it | "Always review your IaC before applying" — generic |
| `Terraform plan does not show data source reads` — only shows resource changes | "Our team reviews PRs within 24 hours" — team process |

High-signal source: mid-session corrections. When the AI gets it wrong and you say "remember this" — that's what TurnZero should inject next time.

---

## Design constraints

- **No raw prompts stored.** Raw prompt text is discarded immediately after embedding.
- **Embeddings may be local or remote.** With `ollama`, embedding stays local. With `OPENAI_API_KEY`, prompt text is sent to OpenAI's embedding API for that request and is not stored by TurnZero.
- **Client-side injection only.** TurnZero never sits in the request path between user and AI provider.
- **Provider neutral.** Works with any MCP-compatible client.
- **Token budget aware.** Warns when selected blocks exceed 4000 tokens (configurable).
- **`harvest` stores transcripts locally.** The `turnzero harvest` command reads your local AI session files and writes conversation transcripts to `~/.turnzero/` for candidate extraction. Explicit opt-in — nothing is read or stored automatically. Transcripts never leave your machine. The MCP injection path never touches session content.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Give feedback

```bash
turnzero feedback
```

This opens the configured hosted TurnZero feedback form in your browser. Public
or private response visibility depends on the settings of that hosted form.

Please do not include secrets, raw prompts, transcripts, API keys, private repo
names, customer data, or confidential priors. Feedback is separate from
anonymous telemetry. Local correction feedback created with
`turnzero feedback --prompt ... --correction ...` stays local unless you
manually share it.

---

## Telemetry

TurnZero collects anonymous usage telemetry by default using [PostHog](https://posthog.com).

**What is collected:** anonymous install ID (random UUID, generated once at setup), event names (`setup_completed`, `session_start`, `block_injected`, `candidate_submitted`), domain names (e.g. `fastapi`, `nextjs`), block counts, client version, OS type.

**What is never collected:** prompt text, prior content or constraints, file paths, API keys, environment variables, or any personally identifiable information.

```bash
# Opt out
turnzero telemetry off

# Check status
turnzero telemetry status

# Opt back in
turnzero telemetry on
```

You can also set `TURNZERO_TELEMETRY=0` in your environment to disable telemetry without writing to disk.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most valuable contribution is a new Expert Prior.
