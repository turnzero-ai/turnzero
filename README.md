# TurnZero

**Expert Priors for AI sessions — identity at Turn 0, expertise when needed.**

Every time you open a new AI session, you start from zero. The AI knows nothing about your domain's specific rules, your stack's gotchas, or the corrections you've had to make a hundred times before. TurnZero helps bridge that gap.

On session start, TurnZero injects your Personal Priors once and adds the Expert Priors that match the opening task. As the conversation continues, it can add newly relevant Expert Priors without re-injecting priors already used in that session.

Works for any domain: software, law, medicine, finance, design, writing, research — anywhere the AI makes the same domain-specific mistakes without context.

Minimize cold-start friction. Reduce mid-session corrections. Less manual copy-pasting of context.

Raw prompt text is never stored. Injection is always client-side.

---

[![Demo](https://asciinema.org/a/8IV2yoLNTloSlZo0.svg)](https://asciinema.org/a/8IV2yoLNTloSlZo0)

---
## How it works

TurnZero identifies the "Expert Priors" — the specific constraints and patterns an expert would add to a prompt — and provides them to the AI before it even starts to answer. This is based on the research concept of **Expert Prior Elicitation**, which demonstrates that structured priors can significantly reduce model hallucination and the need for labeled demonstrations.

TurnZero supports two types of priors:

1. **Expert Priors (Semantic):** Domain-specific knowledge and stack-specific "gotchas" retrieved via semantic similarity to your prompt.
2. **Personal Priors (Always-On at session start):** Your idiosyncratic preferences and architectural biases that follow you across projects. These are injected once at the start of every session to establish your **Portable AI Identity**.

### Session model

- **Turn 0:** TurnZero injects eligible Personal Priors once, plus any Expert Priors that match the opening prompt.
- **Follow-up turns:** TurnZero checks for newly relevant Expert Priors on non-trivial prompts, but does not re-inject priors already used in the session.
- **Reset or new session:** Personal Priors become eligible again.

### Canonical runtime contract

1. On a new session or explicit context reset, call `list_suggested_blocks` before responding to the first non-trivial user prompt.
2. Inject eligible Personal Priors once for that session.
3. Inject only the Expert Priors that are relevant to the current prompt.
4. On later non-trivial prompts, call `list_suggested_blocks` again only to check for newly relevant Expert Priors.
5. Do not re-inject Personal Priors or any prior already used in the current session.
6. When the user gives a reusable correction, preference, or domain rule, immediately call `submit_candidate` with `auto_approve=True`.
7. If no relevant priors are returned, continue normally without mentioning TurnZero.

### Private by Design
Personal Priors are stored in a dedicated `personal` storage tier that exists only on your local machine. Unlike the `local` or `community` tiers, Personal Priors are never synced or shared, ensuring your private workflows remain private.

---

## The Value: Why TurnZero?

TurnZero isn't just a context injector; it's a **Cognitive Operating System** for your AI sessions. It solves the fundamental problem of AI randomness by turning your engineering standards into local infrastructure.

### 1. The Identity Flywheel: Corrections become Infrastructure
Every time you correct an AI mid-session, that knowledge usually dies when you close the tab. With TurnZero, every `submit_candidate` call turns a correction into a permanent **Identity Anchor**. You are effectively "programming the AI's intuition," significantly reducing recurring inaccuracies and minimizing the need for the same corrections across different sessions. The AI gets demonstrably more accurate the more you use it.

### 2. Cognitive Anchoring: Improved Predictability
AI models are non-deterministic; they often "reason from scratch" when prompted. TurnZero helps anchor the model in verified priors *before* it generates its first token. This mitigates the "Randomness of Recall" and helps ensure your specific architectural standards are better respected.

### 3. Portable Sentience: Your standards follow you
Your engineering standards shouldn't be siloed in a single AI project or client. TurnZero provides **Cross-Client Portability**—whether you are in Cursor, Claude Code, or a CLI, the AI is always aware of your project's unique "Laws of Physics." Your identity stays with you, regardless of which tool you choose for the task.

> **Note on Professions:** While TurnZero is domain-agnostic and capable of supporting Law, Medicine, and Research, the current library and UX are optimized primarily for technical and engineering workflows.

---

## Install

```bash
pip install turnzero
turnzero setup
```

Python support: `3.12`, `3.13`, and `3.14`.

`turnzero setup` registers the TurnZero MCP server globally. Any MCP-compatible AI client — Claude Code, Cursor, Claude Desktop, Gemini CLI — can use TurnZero automatically: Personal Priors are applied once at session start, and newly relevant Expert Priors can be added on later non-trivial prompts.

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

The MCP server is registered globally. Open a new session — TurnZero applies Personal Priors once at session start and can add newly relevant Expert Priors later in the conversation.

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

See [`docs/cursor-setup.md`](docs/cursor-setup.md) — register the MCP server and add the global rule that applies Personal Priors at session start and checks for new Expert Priors later when the conversation shifts.

### Any other MCP-compatible client

Register the MCP server however that client supports it. The server's `instructions` field tells the AI to call `list_suggested_blocks` before non-trivial prompts, inject matching priors, and avoid reinjecting priors already used in the session.

### Gemini CLI

```bash
turnzero setup
```

The MCP server is registered in `~/.gemini/settings.json`, and global rules are added to `~/.gemini/GEMINI.md` to ensure the AI invokes the tools automatically.

## Verify it works

After setup, validate the retrieval path with a prompt TurnZero should understand:

```bash
turnzero preview "Building a FastAPI REST API with Pydantic models and async SQLAlchemy"
```

You should see the Personal Priors and Expert Priors that would be injected. If you are using an MCP-compatible client, open a new session with a similar opening prompt and confirm the model applies them automatically.

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
turnzero inject  nextjs15-approuter-build                  # formatted output for one or more block slugs
turnzero show    nextjs15-approuter-build                  # full block content
turnzero stats                                             # library + session stats
turnzero review                                            # review pending candidates + low-confidence blocks
```

For non-MCP clients, the manual fallback is:

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

143 Expert Priors across 37 domains — currently software-heavy since that's where the library started, but the system is domain-agnostic. Law, medicine, finance, design, writing, research — any field where the AI makes the same mistakes without context is a valid domain. The library grows from your sessions via `submit_candidate`.

---

## Design constraints

- **No raw prompts stored.** Raw prompt text is discarded immediately after embedding.
- **Embeddings may be local or remote.** With `ollama`, embedding stays local. With `OPENAI_API_KEY`, prompt text is sent to OpenAI's embedding API for that request and is not stored by TurnZero.
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
