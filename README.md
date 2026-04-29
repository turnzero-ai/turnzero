# TurnZero

**Expert Priors for AI sessions — injected automatically at Turn 0.**

Every time you open a new AI session, you start from zero. The AI knows nothing about your domain's specific rules, your stack's gotchas, or the corrections you've had to make a hundred times before. TurnZero fixes that.

It embeds your opening prompt, finds the most relevant Expert Priors for your domain, and injects them before the AI responds — so the model already knows the right answer before it has a chance to get it wrong.

Works for any domain: software, law, medicine, finance, design, writing, research — anywhere the AI makes the same domain-specific mistakes without context.

No cold starts. No mid-session corrections. No copy-pasting context.

Raw prompt text is never stored. Injection is always client-side.

---

[![Demo](https://asciinema.org/a/8IV2yoLNTloSlZo0.svg)](https://asciinema.org/a/8IV2yoLNTloSlZo0)

---
## How it works

TurnZero identifies the "Expert Priors" — the specific constraints and patterns an expert would add to a prompt — and ensures the AI knows them before it even starts to answer. This is based on the research concept of **Expert Prior Elicitation**, which demonstrates that structured priors can significantly reduce model hallucination and the need for labeled demonstrations.

TurnZero supports two types of priors:

1. **Expert Priors (Semantic):** Domain-specific knowledge and stack-specific "gotchas" retrieved via semantic similarity to your prompt.
2. **Personal Priors (Always-On):** Your idiosyncratic preferences and architectural biases that follow you across projects. These are **auto-injected** at the start of every session (Turn 0) to establish your **Portable AI Identity**.

### Private by Design
Personal Priors are stored in a dedicated `personal` storage tier that exists only on your local machine. Unlike the `local` or `community` tiers, Personal Priors are never synced or shared, ensuring your private workflows remain private.

```
You type: "I'm building a FastAPI async API with PostgreSQL"
                            │
                            ▼
           TurnZero identifies the relevant Expert Priors
           AND unconditionally injects your Personal Priors
                            │
                            ▼
           AI starts Turn 1 already fully aligned
```

         Injected before the AI responds:
         ✓ Use async def — sync def blocks the event loop
         ✓ expire_on_commit=False with AsyncSession (prevents MissingGreenlet)
         ✓ lifespan= not @app.on_event (deprecated since 0.93)
         ✓ Pydantic v2: model_config = ConfigDict(...), not inner class Config
```

An **Expert Prior** is the delta between a naive prompt and an expert prompt — what a senior developer would silently add before hitting send.

---

## Install

```bash
pip install turnzero
turnzero setup
```

Python support: `3.12`, `3.13`, and `3.14`.

`turnzero setup` registers the TurnZero MCP server globally. Any MCP-compatible AI client — Claude Code, Cursor, Claude Desktop, Gemini CLI — will automatically call `list_suggested_blocks` on Turn 0 and inject the relevant Expert Priors. No further configuration needed.

**Embedding backend — pick one:**

| Option | Setup |
|---|---|
| ollama (local, free, private) | `ollama serve && ollama pull nomic-embed-text` |
| OpenAI API | `export OPENAI_API_KEY=sk-...` |

If you want local embeddings, install `ollama`, start it with `ollama serve`, and pull the embedding model with `ollama pull nomic-embed-text`. TurnZero no longer ships a separate local Python embedding stack.

---

## IDE Integration

### Claude Code

```bash
turnzero setup
```

The MCP server is registered globally. Open a new session — TurnZero calls `list_suggested_blocks` automatically on Turn 0.

```bash
# Optional: also install the UserPromptSubmit hook for guaranteed injection
# regardless of model behaviour
turnzero setup --with-hook
```

### Claude Code (manual)

```bash
claude mcp add turnzero /path/to/.venv/bin/turnzero-mcp --scope user
```

### Cursor

See [`docs/cursor-setup.md`](docs/cursor-setup.md) — register the MCP server and add the global rule that triggers auto-injection on Turn 0.

### Any other MCP-compatible client

Register the MCP server however that client supports it. The server's `instructions` field tells the AI to call `list_suggested_blocks` at the start of every session. If the client surfaces MCP server instructions to the model, injection is automatic.

### Gemini CLI

```bash
turnzero setup
```

The MCP server is registered in `~/.gemini/settings.json`, and global rules are added to `~/.gemini/GEMINI.md` to ensure the AI invokes the tools automatically.

---

## How the library grows

TurnZero learns from your sessions. When the AI gets something wrong and you correct it mid-session, that correction is a high-signal "Expert Prior" candidate.

```
"No, use asyncpg not psycopg2 — psycopg2 blocks the event loop"
              │
              ▼
    AI detects correction, suggests a new Expert Prior
              │
              ▼
    Confidence scoring + manual review safety layer
              │
              ▼
    Injected in every future session matching that stack
```

No background daemons required. The AI used in the session performs the extraction, identifying the exact moments where domain-specific knowledge saved the day. AI-submitted blocks are automatically down-weighted until they gain confidence through reinforcement.


---

## CLI

```bash
turnzero setup                                             # register MCP, build index
turnzero preview "build a Next.js 15 app with Supabase"   # preview what would inject
turnzero query   "build a Next.js 15 app with Supabase"   # ranked block list
turnzero inject  "build a Next.js 15 app with Supabase"   # formatted output for any AI
turnzero show    nextjs15-approuter-build                  # full block content
turnzero stats                                             # library + session stats
turnzero review                                            # review pending candidates + low-confidence blocks
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

143 Expert Priors across 37 domains — currently software-heavy since that's where the library started, but the system is domain-agnostic. Law, medicine, finance, design, writing, research — any field where the AI makes the same mistakes without context is a valid domain. The library grows from your sessions via `submit_candidate`.

---

## Design constraints

- **No raw prompts stored.** Only embeddings persist — raw text is discarded immediately after embedding.
- **Client-side injection only.** TurnZero never sits in the request path between user and AI provider.
- **Provider neutral.** Works with any MCP-compatible client — Claude Code, Cursor, Claude Desktop, and others.
- **Token budget aware.** Warns when selected blocks exceed 4000 tokens (configurable).
- **`harvest` stores transcripts locally.** The `turnzero harvest` command reads your local AI session files and writes conversation transcripts to `~/.turnzero/` for candidate extraction. This is an explicit opt-in step — nothing is read or stored automatically. Transcripts never leave your machine. The MCP injection path (the default) never touches session content at all.

---

## What makes a good Expert Prior

**The test:** *Would a stranger on the same stack, facing the same problem, be better off knowing this before Turn 0?*

| Good | Bad |
|---|---|
| `Do not use getServerSideProps in App Router` — API removed in Next.js 13 | "Use PyCharm" — personal preference |
| `expire_on_commit=False required with AsyncSession` — raises MissingGreenlet without it | "Don't commit API keys" — generic noise |
| `Supabase RLS is disabled by default on new tables` — silently breaks auth | "Use Docker Compose for local dev" — workflow choice |
| `Swiss non-compete clauses unenforceable beyond 3 years` — jurisdiction-specific rule | "Be more concise" — personal style feedback |
| `eGFR staging differs between CKD-EPI 2009 and 2021` — clinically significant threshold | "Always double-check your sources" — generic |
| `Options Delta accelerates near expiration (gamma effect)` — mispricing risk without it | "Our team reviews PRs within 24 hours" — team convention |

High-signal source: mid-session corrections. When the AI gets it wrong and you say "remember this" — that's exactly what TurnZero should inject next time.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most valuable contribution is a new Expert Prior.
