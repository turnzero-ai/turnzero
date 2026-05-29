# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

TurnZero is at **v0.17.0** (not yet published — proxy sprint in progress on `feat/proxy-p1-core`).

- **Public SSOT:** [ROADMAP.md](ROADMAP.md) (Vision and Phases)
- **Internal SSOT:** `internal/PROJECT_STATE.md` (Debt, Active Tickets, Launch Gate — **GITIGNORED**)

- 152 Expert Priors across 40 domains shipped in wheel
- 447 tests passing; Hit Rate@3 = 0.815 on validation set
- Primary injection path: MCP server + local HTTP proxy (`turnzero proxy serve`, v0.17.0)
- Hybrid Model: Personal Priors once per session, Expert Priors when newly relevant.
- Support for: Claude Code, Cursor, Claude Desktop, Codex, Gemini CLI
- AI-driven learning: `submit_candidate` MCP tool — no harvest daemon needed
- All thresholds unified at 0.70 (CLI, MCP, retrieval)
- Embedding: fallback chain — ONNX in-process (`pip install onnxruntime tokenizers`, ~520 MB model) → ollama → OpenAI
- Agentic benchmark: `python -m tests.evals.benchmark` — Claude/Gemini/Codex, 7 scenarios

## What TurnZero Does

TurnZero eliminates cold-start friction in AI sessions by injecting relevant context at the start of a session. It uses a dual-injection model:
1. **Expert Priors:** Domain-specific knowledge retrieved via semantic similarity.
2. **Personal Priors:** Idiosyncratic user preferences and standards injected **unconditionally** at session start (Turn 0) to establish a **Portable AI Identity**.

Raw prompt text is **never stored** — only embeddings. Injection is always client-side.

## Tech Stack

- **Language**: Python 3.12+
- **Retrieval Engine**: Hybrid vector + heuristic similarity
- **CLI framework**: Typer
- **Integration**: MCP-native architecture
- **Testing**: pytest + Hit Rate@K evaluation harness (Unit tests: fast loop; Integration tests: -m integration)

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

## Workflow

### Plan before multi-step work
Enter plan mode (`EnterPlanMode`) for any task spanning 3+ files, touching the MCP contract, or making architectural decisions. Write the plan, get alignment, then implement. Don't start coding first.

### Use subagents for exploration
Delegate to Explore or general-purpose agents for: codebase audits, finding all callers of a function, checking file structure violations, researching across many files. Keeps main context clean for implementation.

### Capture corrections immediately
Any mistake the user corrects → call `submit_candidate` immediately, before the next step. Don't defer to end of session. TurnZero is the lessons system — use it.

### Stage commits explicitly
Never `git add -A` or `git add .`. Always stage by filename. Run `git status --short` and verify every staged path before committing. `data/` contains both repo assets and runtime artifacts.

### Index rebuild procedure
Never `TURNZERO_DATA_DIR=data turnzero index build` — falls back to Ollama silently. Always use isolated `/tmp` build dir with Python 3.12. See `internal/PROJECT_STATE.md` → Known Build Constraints.

---

## Key Design Constraints

- **No raw prompts stored ever.** Only embeddings persist. Raw text is discarded immediately after embedding.
- **Injection is always client-side.** TurnZero must never intercept the live request path between user and AI provider.
- **Token budget awareness.** Blocks carry `context_weight` estimates. Warn when total exceeds 4000 tokens (configurable).
- **Provider neutrality.** Works with any MCP-compatible AI client.
- **Domain-agnostic.** Any field where the AI makes domain-specific mistakes — not just software.
- **Descriptive block IDs.** Slugs like `nextjs15-approuter-build` — never mutate in place; create a new version.
- **Minimal dependencies.** Prefer httpx (already bundled) over adding new packages. Less coupling = less breakage.

---

## Coding Standards

### Python style
- Python 3.12+ — use native syntax (`X | Y`, `match`, f-strings)
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
- Retrieval quality gate: Hit Rate@3 ≥ 0.70 on `tests/validation_set.json` — run `turnzero validate` before any retrieval change
- Test the public contract, not internals. Mock nothing that can be tested with real data

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

### Quality gates (automated)
Pre-commit hook enforces ruff + mypy + pytest on every commit.
Pre-push hook enforces docs consistency, layer audit, and Claude code review before code reaches GitHub.
Install once: `make install-hooks`. Bypass only in emergencies: `git push --no-verify`.

### Versioning

**When to bump what:**

| Bump | Rule | Examples |
|------|------|---------|
| `MAJOR` | Breaking change — users must act after upgrade | CLI command renamed/removed, MCP tool signature changed, block schema field removed, config format incompatible |
| `MINOR` | New capability OR structural growth | New CLI command, new MCP tool, new AI client supported, internal restructuring touching ≥5 files or introducing new modules/layers, accumulated patches that together represent more than isolated fixes |
| `PATCH` | Isolated fix or trivial change | Single bug fix, doc-only update, refactor touching ≤4 files with no structural change, test additions |

**Hygiene rule:** Patch count should not reach 10 within a minor version. If it does, retrospectively ask whether accumulated changes deserved a minor bump. Goal: patch stays in single digits.

- Bump only in `pyproject.toml` — consumed via `importlib.metadata`
- Version bump is a **dedicated commit immediately before `hatch publish`** — never mixed into feature work
- Tag every PyPI release: `git tag vX.Y.Z`

### Release checklist (before every `hatch publish`)
1. All tests green: `pytest`
2. Lint + types clean: `ruff check . && mypy turnzero`
3. Retrieval quality gate: `turnzero validate` — Hit Rate@3 must be ≥ 0.70
4. `data/index.jsonl` rebuilt from current blocks: `turnzero index build`
5. Version bumped in `pyproject.toml` in its own commit
6. Tagged: `git tag vX.Y.Z`
7. Confirm with maintainer before running `hatch publish`

### Doc sync checklist (every release)
- `SECURITY.md` — update supported version table to match new version
- `CLAUDE.md` — update version and test count in Project Status header
- `README.md` / `FAQ.md` — scan for client list; add any newly supported client; verify install steps still work
- `ROADMAP.md` Maintenance & Done — add completed milestone with version tag
- `internal/PROJECT_STATE.md` — mark completed tickets, add new debt found
- `internal/ARCHITECTURE.md` — update `Last verified` line to new version/commit; verify Module Map and MCP Tool Surface are accurate
- `BENCHMARK.md` — add results row if benchmark was run this sprint; keep consolidated three-agent table current

### Block YAML schema
- Slug: descriptive kebab-case, version-anchored where relevant (`nextjs15-approuter-build`)
- Never mutate a slug for a breaking change — create a new slug
- Every `anti_patterns` entry must start with `"Do not"`
- `context_weight` = realistic token estimate (word_count × 4)
- `confidence` = 0.0-1.0; curated blocks = 1.0, AI-submitted start lower
- `archived` = set to true to exclude from retrieval
- `tier` = local | community | team | personal (auto-populated from storage path)
- `last_verified` = ISO date — update whenever the block is re-verified
- `verification_level` = curated | observed | synthetic
- `rationale` = required if `anti_patterns` are present; explains the "why" behind the rules.

### TurnZero MCP tools
- Tool names: `snake_case` verbs
- `list_suggested_blocks`: Call on Turn 0 to retrieve the **Portable AI Identity** (Personal) and relevant domain knowledge (Expert).
- `submit_candidate`: Use `is_personal=True` for idiosyncratic preferences and `is_personal=False` for technical/domain truths.
- `reset_session`: Call when the user requests a context clear or fresh start.
- Every tool must catch `RuntimeError` from embedding and return a structured error dict — never crash the MCP server
- New tools need a matching test in `tests/test_mcp_server.py`
