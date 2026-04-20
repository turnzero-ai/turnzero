# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

TurnZero is at **v0.2.2** (PyPI live) / **v0.2.3** (GitHub, pending PyPI token).

- 74 blocks shipped in wheel, 123 blocks in Darijo's local library
- Any domain — software, law, medicine, finance, design, writing, research
- 135 tests passing; Hit Rate@3 = 1.00 on validation set
- Primary injection path: MCP server (hook is optional `--with-hook`)
- AI-driven learning: `submit_candidate` MCP tool — no harvest daemon needed
- All thresholds unified at 0.75 (CLI, hook, MCP, retrieval)
- Embedding: httpx-only fallback chain — ollama (via OLLAMA_HOST) → sentence-transformers → OpenAI

## What TurnZero Does

TurnZero eliminates cold-start friction in AI sessions by injecting relevant expert knowledge at the start of a session. It uses a multi-layered retrieval system to ensure that the AI is aligned with the user's technical environment and intent before the first response.

Raw prompt text is **never stored** — only embeddings. Injection is always client-side.

## Tech Stack

- **Language**: Python 3.12+
- **Retrieval Engine**: Hybrid vector + heuristic similarity
- **CLI framework**: Typer
- **Integration**: MCP-native architecture
- **Testing**: pytest + Hit Rate@K evaluation harness

## Commands

```bash
# Install (dev)
pip install -e ".[dev]"

# Install (end user)
pipx install turnzero

# Setup (registers MCP server, builds index)
turnzero setup

# CLI
turnzero --version
turnzero query "<opening prompt>"
turnzero preview "<opening prompt>"
turnzero stats
turnzero review
turnzero index build

# Harvest from past sessions
turnzero harvest

# Tests
pytest
```

## Key Design Constraints

- **No raw prompts stored ever.** Only embeddings persist. Raw text is discarded immediately after embedding.
- **Injection is always client-side.** TurnZero must never intercept the live request path between user and AI provider.
- **Token budget awareness.** Blocks carry `context_weight` estimates. Warn when total exceeds 4000 tokens (configurable).
- **Provider neutrality.** Works with any MCP-compatible AI client.
- **Domain-agnostic.** Any field where the AI makes domain-specific mistakes — not just software.
- **Descriptive block IDs.** Slugs like `nextjs15-approuter-build` — never mutate in place; create a new version.
- **Minimal dependencies.** Prefer httpx (already bundled) over adding new packages. Less coupling = less breakage.

---

## Session Workflow (Claude must follow these rules every session)

### 1. Load full memory at session start
A `SessionStart` hook automatically injects all memory files into context. At the start of every session, treat that loaded memory as ground truth for project state — do not rely on stale knowledge from training data.

### 2. Keep memory and docs in sync
After any strategic decision, architectural change, or significant implementation:
- Update the relevant memory file(s) in `~/.claude/projects/-Users-darijomilicevic-Development-TurnZero/memory/`
- Update `CLAUDE.md` if project status, commands, or constraints changed
- Update `ROADMAP.md` if phase items were completed or priorities shifted
Do this during the session, not as an afterthought at the end.

### 3. Maintain test coverage
When adding or changing behaviour:
- Check whether existing tests cover the changed code paths
- If not, add targeted tests before closing out the task
- Tests live in `tests/` — run with `pytest` via `source .venv/bin/activate && pytest`

### 4. Always ask before pushing to GitHub or publishing to PyPI
**Never run `git push` or `hatch publish` without explicit confirmation from the user first.**
State what will be pushed and where, then wait for a yes. This applies even when the user says "deploy" or "ship it" — confirm the exact action first.
