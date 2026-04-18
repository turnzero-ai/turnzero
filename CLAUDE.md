# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

TurnZero is at **v0.2.0**. Core engine, MCP server, CLI, and IDE integrations are operational.

- 122+ Expert Priors across 25 domains
- Any domain — software, law, medicine, finance, design, writing, research
- Tests passing; Hit Rate@3 = 1.00 on validation set
- Primary injection path: MCP server (hook is optional `--with-hook`)
- AI-driven learning: `submit_candidate` MCP tool — no harvest daemon needed

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
# Install
pip install -e ".[dev]"

# Setup (registers MCP server, builds index)
turnzero setup

# CLI
turnzero query "<opening prompt>"
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
