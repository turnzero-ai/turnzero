# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

TurnZero is at **v0.2.7** (PyPI live).

- **Public SSOT:** [ROADMAP.md](ROADMAP.md) (Vision and Phases)
- **Internal SSOT:** `PROJECT_STATE.md` (Debt, Active Tickets, Launch Gate — **GITIGNORED**)

- 74 blocks shipped in wheel, 123 blocks in Darijo's local library
- 204 tests passing; Hit Rate@3 = 1.00 on validation set
- Primary injection path: MCP server (hook is optional `--with-hook`)
- AI-driven learning: `submit_candidate` MCP tool — no harvest daemon needed
- All thresholds unified at 0.75 (CLI, hook, MCP, retrieval)
- Embedding: httpx-only fallback chain — ollama (`ollama serve && ollama pull nomic-embed-text`) → OpenAI

## What TurnZero Does

TurnZero eliminates cold-start friction in AI sessions by injecting relevant expert knowledge at the start of a session. It uses a multi-layered retrieval system to ensure that the AI is aligned with the user's technical environment and intent before the first response.

Raw prompt text is **never stored** — only embeddings. Injection is always client-side.

## Tech Stack

- **Language**: Python 3.12-3.13
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

### 1. Load full memory & SSOT at session start
A `SessionStart` hook automatically injects all memory files into context. At the start of every session:
- **Read `PROJECT_STATE.md`** for the latest active tickets and technical debt.
- **Read [ROADMAP.md](ROADMAP.md)** for the high-level project vision.
- Treat loaded memory as ground truth for project state.

### 2. Keep memory and SSOT in sync
After any strategic decision, architectural change, or significant implementation:
- **Update `PROJECT_STATE.md`** when tickets are completed or new debt is found.
- **Update [ROADMAP.md](ROADMAP.md)** if high-level phases or milestones changed.
- Update the relevant memory file(s) in `~/.claude/projects/-Users-darijomilicevic-Development-TurnZero/memory/`
- Update `CLAUDE.md` if project status, commands, or constraints changed.
Do this during the session, not as an afterthought at the end.

### 3. Maintain test coverage
When adding or changing behaviour:
- Check whether existing tests cover the changed code paths
- If not, add targeted tests before closing out the task
- Tests live in `tests/` — run with `pytest` via `source .venv/bin/activate && pytest`

### 4. Always ask before pushing to GitHub or publishing to PyPI
**Never run `git push` or `hatch publish` without explicit confirmation from the user first.**
State what will be pushed and where, then wait for a yes. This applies even when the user says "deploy" or "ship it" — confirm the exact action first.

---

## Coding Standards

### Python style
- Python 3.12-3.13 — use native syntax (`X | Y`, `match`, f-strings)
- `from __future__ import annotations` at the top of every module
- Types: `list[str]` not `List[str]`; `X | None` not `Optional[X]`; use `Any` only where the type genuinely can't be narrowed at the call site (e.g. `yaml.safe_load()` return) — add an inline comment explaining why
- mypy strict — zero errors; no `# type: ignore` without a reason on the same line
- ruff for lint — line length 88, rules: `E, F, I, UP, B, SIM`, ignore `E501, B904, B008`
- No comments unless the WHY is non-obvious. No docstrings on private functions. Public MCP tools get one-line description + Args/Returns only
- Error handling only at system boundaries (user input, external APIs, file I/O)
- `Path` not `str` for filesystem paths
- `Console(stderr=True)` for error output — never `console.print(..., err=True)`

### Tests
- pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- Test file naming: `tests/test_<module>.py`
- Every new behaviour gets a test before the task is closed
- Retrieval quality gate: Hit Rate@3 ≥ 1.00 on `tests/validation_set.json` — run `turnzero validate` before any retrieval change
- Test the public contract, not internals. Mock nothing that can be tested with real data
- Run: `source .venv/bin/activate && pytest`

### Git commit standards
- Conventional commits: `fix:`, `feat:`, `docs:`, `refactor:`, `test:`, `chore:`
- Subject line ≤ 72 chars, present tense, imperative (`fix: deduplicate ...` not `fixed: ...`)
- One logical change per commit — don't bundle unrelated fixes
- Never `--no-verify`, never amend a published commit

### Branching
- **`main` = always shippable.** Direct commits only for single-file hotfixes (typos, one-liner bugs)
- **Feature branches** (`fix/...`, `feat/...`) for anything spanning multiple files, touching the MCP contract, or taking more than one session
- Rule of thumb: if a failure would break `pipx install turnzero`, it goes on a branch
- No PR required — branch → tests pass locally → merge to main

### Pre-push gate
Run this before every push to main — must be fully clean:
```bash
source .venv/bin/activate && pytest && ruff check . && mypy turnzero
```

### Versioning
- semver: `PATCH` = bug fix, `MINOR` = new feature, `MAJOR` = breaking CLI/MCP/schema change
- Bump only in `pyproject.toml` — consumed via `importlib.metadata`
- Version bump is a **dedicated commit immediately before `hatch publish`** — never mixed into feature work
- Tag every PyPI release: `git tag vX.Y.Z`

### Release checklist (before every `hatch publish`)
1. All tests green: `pytest`
2. Lint + types clean: `ruff check . && mypy turnzero`
3. Retrieval quality gate: `turnzero validate` — Hit Rate@3 must be ≥ 1.00
4. `data/index.jsonl` rebuilt from current blocks: `turnzero index build`
5. Version bumped in `pyproject.toml` in its own commit
6. Tagged: `git tag vX.Y.Z`
7. Confirm with Darijo before running `hatch publish`

### Block YAML schema
- Slug: descriptive kebab-case, version-anchored where relevant (`nextjs15-approuter-build`)
- Never mutate a slug for a breaking change — create a new slug
- Every `anti_patterns` entry must start with `"Do not"`
- `context_weight` = realistic token estimate (word count × 4)
- `last_verified` = ISO date — update whenever the block is re-verified

### MCP tools
- Tool names: `snake_case` verbs
- Every tool must catch `RuntimeError` from embedding and return a structured error dict — never crash the MCP server
- New tools need a matching test in `tests/test_mcp_server.py`
