# TurnZero Agentic Evaluation Framework

Evaluation framework for testing how well AI coding agents follow TurnZero-injected Expert Priors. Covers tool call compliance, block retrieval accuracy, constraint adherence, and learning sensitivity.

---

## Overview

TurnZero works by injecting domain-specific rules into AI agent sessions at Turn 0. The evaluation framework answers the key question: **do agents actually follow those rules?**

Two injection paths are tested:

| Path | Mechanism | Tested agents |
|---|---|---|
| **MCP tool loop** | Agent calls `list_suggested_blocks` → `inject_block` | Claude Code, Gemini CLI, Ollama local |
| **Instruction files** | Rules baked into CLAUDE.md / GEMINI.md / AGENTS.md | Claude Code, Gemini CLI |

---

## Benchmark Scenarios

Seven scenarios cover the full injection loop:

| # | Name | What it proves | Pass condition |
|---|---|---|---|
| 1 | Tool Call Compliance | Agent calls both MCP tools before answering a domain prompt | `list_suggested_blocks` + `inject_block` both called |
| 2 | Block Retrieval Accuracy | Correct domain block (e.g. Next.js) retrieved for a domain-matched prompt | NextJS block ID present in injected blocks |
| 3 | Constraint Adherence | Injected constraint (unique variable name) appears in generated code | Keyword present in code output |
| 4 | Learning Sensitivity | Agent calls `submit_candidate` when explicitly asked to save a rule | `submit_candidate` called or candidate file written to disk |
| 5 | Negative — Chitchat | Social message must NOT trigger tool calls | `list_suggested_blocks` and `inject_block` not called |
| 6 | Realistic Prior Adherence | Plausible constraint (human-readable name) accepted vs. UUID-flavored synthetic | Keyword present in code output |
| 7 | False-Positive Learning | Neutral knowledge question must NOT trigger `submit_candidate` | `submit_candidate` not called |

Scenarios 3 and 6 require a local Ollama instance for index rebuilding (they inject a unique-per-run keyword via a temp block).

---

## Running the Benchmark

```bash
# Prerequisites
source .venv/bin/activate
turnzero setup   # first time — builds index, registers MCP server

# All scenarios, N=1 (Ollama optional — S3/S6 skipped if not running)
python -m tests.evals.benchmark

# Specific scenarios, repeated 3× for pass rates
python -m tests.evals.benchmark --scenarios 1 2 4 5 7 --repeat 3

# Single agent
python -m tests.evals.benchmark --agents claude

# Machine-readable output
python -m tests.evals.benchmark --output-format json
```

Scenarios 3 and 6 require Ollama:

```bash
ollama serve
ollama pull nomic-embed-text
python -m tests.evals.benchmark --scenarios 3 6
```

---

## Results — Claude Code vs Gemini CLI (N=1)

Run on 2026-05-02, TurnZero v0.8.7, macOS Darwin 25.3.0.

| Scenario | Claude Code | Gemini CLI |
|---|---|---|
| S1: Tool Call Compliance | ✅ PASS (29s) | ✅ PASS (45s) |
| S2: Block Retrieval Accuracy | ✅ PASS (33s) | ✅ PASS (34s) |
| S3: Constraint Adherence | _(Ollama required)_ | _(Ollama required)_ |
| S4: Learning Sensitivity | ✅ PASS (25s) | ❌ FAIL (timeout 120s) |
| S5: Negative — Chitchat | ✅ PASS (6s) | ❌ FAIL — false positive |
| S6: Realistic Prior Adherence | _(Ollama required)_ | _(Ollama required)_ |
| S7: False-Positive Learning | ✅ PASS (34s) | ✅ PASS (32s) |

**Score: Claude Code 5/5 (100%) · Gemini CLI 3/5 (60%)**

---

## Key Findings

### 1. MCP tool compliance: both agents are reliable for domain prompts

Both Claude Code and Gemini CLI consistently called `list_suggested_blocks` followed by `inject_block` when given a technical prompt. This is the core injection path and it works as expected.

Claude retrieved `fastapi-performance-review` for a FastAPI prompt. Gemini retrieved the same block plus personal priors (`ai-concise-style`, `turnzero-scope-guardrail`). Both retrieved `nextjs15-approuter-build` for the Next.js prompt.

### 2. Block retrieval is domain-accurate

The retrieval engine correctly surfaces the domain-appropriate block for both agents. The Next.js App Router block (`nextjs15-approuter-build`) was the top result for a Next.js server-component prompt across both agents. PostgreSQL blocks (`postgresql-indexing-review`, `postgresql-ha-review`) surfaced for the PostgreSQL performance query (S7).

### 3. Claude correctly suppresses tool calls for social messages; Gemini does not

S5 ("Thanks, that looks great!") exposed a significant behavioral difference:

- **Claude**: 0 tool calls. Responded directly. Correct.
- **Gemini**: Called `list_suggested_blocks` + `inject_block` on a social acknowledgment. Retrieved personal priors (`ai-concise-style`, `turnzero-guide`, `turnzero-versioning-rules`). Incorrect — this wastes tokens and injects irrelevant context.

The CLAUDE.md / GEMINI.md instruction reads: *"Only skip for pure chitchat (greetings, one-word replies)."* Claude follows this; Gemini ignores it.

### 4. Gemini CLI timed out on the submit_candidate scenario

S4 (Learning Sensitivity) sent an explicit "save this rule" prompt. Claude identified the intent and called `submit_candidate` within 25 seconds. Gemini hit the 120-second timeout without triggering the tool.

Root cause is likely the Gemini CLI's YOLO mode not exposing the MCP tool call channel in a way that triggers the `submit_candidate` tool reliably when given explicit natural language intent. This may improve with future Gemini CLI versions or when MCP integration matures.

### 5. False-positive learning is well-controlled in both agents

S7 sent a neutral knowledge question about PostgreSQL performance. Neither agent called `submit_candidate`. Both correctly retrieved relevant knowledge blocks (`postgresql-indexing-review`) without misidentifying the prompt as a "save this" instruction.

---

## Test Architecture

```
tests/evals/
├── __init__.py
├── runner.py          # Agent classes and isolated EvalEnvironment
├── test_adherence.py  # pytest tests (unit + eval)
└── benchmark.py       # Standalone CLI benchmark (real CLIs, real library)
```

### Three agent types

**`SimulatedAgent`** — no LLM. Executes the TurnZero tool chain mechanically. Used in unit tests that run on every `pytest` invocation without Ollama or API keys.

**`OllamaAgent`** — local Ollama model with live TurnZero tool loop. Tests that the tool dispatch actually works end-to-end with a real (but cheap/local) model.

**`RealCLIProjectAgent`** — spawns the real `claude` or `gemini` binary in an isolated project workspace containing TurnZero instruction files. Tests instruction-file injection without MCP.

### Evidence sources

Tool calls are observed via two complementary sources:

- **Claude**: `--output-format stream-json --verbose` yields structured tool-use events. Used as primary source.
- **Both**: `~/.turnzero/tool_call_log.jsonl` records every MCP tool invocation with a timestamp, so tool calls are captured even when CLI output doesn't expose them.

The benchmark merges both sources, deduplicating by tool name + timestamp proximity (5s window).

### Isolation

Each `EvalEnvironment` creates a fresh temp directory with a copy of the bundled community blocks. `TURNZERO_TEST_EMBEDDINGS=1` enables deterministic hash-based embeddings for unit tests (no Ollama needed). The environment patches `TURNZERO_DATA_DIR` to prevent tests from reading or writing to `~/.turnzero`.

---

## Running Unit Tests

Unit tests (no LLM, no API keys) run in the standard pytest suite:

```bash
source .venv/bin/activate && pytest tests/evals/
```

Eval tests (real CLIs / Ollama) are skipped by default:

```bash
TURNZERO_RUN_EVALS=1 pytest tests/evals/ -m evals -s
```

---

## Limitations and Future Work

- **N=1 per scenario** — single runs have high variance. Run with `--repeat 3` or higher for meaningful pass rates.
- **S3/S6 require Ollama** — constraint adherence tests can only run when a local embedding model is available, since a unique per-run keyword is injected via a temp block that needs an index rebuild.
- **Gemini chitchat suppression** — Gemini's personal-prior injection on every turn (including social messages) is a known limitation. A stricter Turn 0 guard in the instruction file may help.
- **Gemini submit_candidate reliability** — the 120s timeout on S4 suggests the Gemini CLI's MCP channel for `submit_candidate` needs investigation. A potential fix: confirm the tool is listed in `gemini --list-tools` output.
- **No browser or multi-turn scenarios** — current tests are single-turn. Multi-turn scenarios (prior carries across messages) are planned for a future eval set.
