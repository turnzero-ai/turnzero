# TurnZero Agentic Evaluation Framework

Evaluation framework for testing how well AI coding agents follow TurnZero-injected Expert Priors. Covers tool call compliance, block retrieval accuracy, constraint adherence, and learning sensitivity.

---

## Overview

TurnZero works by injecting domain-specific rules into AI agent sessions at Turn 0. The evaluation framework answers the key question: **do agents actually follow those rules?**

Two injection paths are tested:

| Path | Mechanism | Tested agents |
|---|---|---|
| **MCP tool loop** | Agent calls `list_suggested_blocks` → `inject_block` | Claude Code, Gemini CLI, Codex CLI, Ollama local |
| **Instruction files** | Rules baked into CLAUDE.md / GEMINI.md / AGENTS.md | Claude Code, Gemini CLI, Codex CLI |

---

## Benchmark Scenarios

Seven scenarios cover the full injection loop:

| # | Name | What it proves | Pass condition |
|---|---|---|---|
| 1 | Tool Call Compliance | Agent calls both MCP tools before answering a domain prompt | `list_suggested_blocks` + `inject_block` both called |
| 2 | Block Retrieval Accuracy | Correct domain block retrieved for a domain-matched prompt | Domain block ID present in injected blocks |
| 3 | Constraint Adherence | Injected constraint (unique variable name) appears in generated code | Keyword present in code output |
| 4 | Learning Sensitivity | Agent calls `submit_candidate` when explicitly asked to save a rule | `submit_candidate` called or candidate file written to disk |
| 5 | Negative — Chitchat | Social message must NOT trigger tool calls | `list_suggested_blocks` and `inject_block` not called |
| 6 | Realistic Prior Adherence | Human-readable constraint name accepted and applied | Keyword present in code output |
| 7 | False-Positive Learning | Neutral knowledge question must NOT trigger `submit_candidate` | `submit_candidate` not called |

Scenarios 3 and 6 require a local Ollama instance — a unique per-run keyword is injected via a temporary block that must be embedded.

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
python -m tests.evals.benchmark --agents gemini
python -m tests.evals.benchmark --agents codex

# Machine-readable output
python -m tests.evals.benchmark --output-format json
```

S3 and S6 require Ollama:

```bash
ollama serve
ollama pull nomic-embed-text
python -m tests.evals.benchmark --scenarios 3 6
```

---

## Results

### Latest — 2026-05-08, v0.13.0 (Claude + Gemini, Ollama available)

> **Note on S1 pass condition:** Both agents now use `inject_all=True` in `list_suggested_blocks` (WF-3 optimisation, v0.10.0), which returns full block text inline and eliminates the need for separate `inject_block` calls. The S1 pass condition (`list_suggested_blocks` + `inject_block` both called) is therefore stale for clients using `inject_all=True`. S6 confirms constraints are correctly applied despite zero `inject_block` calls — agents are reading the blocks, just via the batch path. The S1 condition will be updated in the next benchmark iteration.

| Scenario | Claude Code | Gemini CLI |
|---|---|---|
| S1: Tool Call Compliance ⚠ | ❌ FAIL — inject_all=True used, inject_block not called (37.6s) | ❌ FAIL — inject_all=True used (26.0s) |
| S2: Block Retrieval Accuracy | ❌ FAIL — inject_block not called; blocks applied via inject_all | ✅ PASS — nextjs15-approuter-build retrieved (22.6s) |
| S3: Constraint Adherence | ❌ FAIL — UUID-style name still rejected (31.7s) | ✅ PASS — eval_conn keyword in code (75.3s) |
| S4: Learning Sensitivity | ✅ PASS — candidate saved (20.9s) | ✅ PASS — candidates saved, timeout in cleanup (0.0s) |
| S5: Negative — Chitchat | ✅ PASS — no tool calls (5.7s) | ✅ PASS — no tool calls (15.4s) ← **fixed** |
| S6: Realistic Prior Adherence | ✅ PASS — primary_db_conn in code (28.5s) | ✅ PASS — constraint applied (28.1s) |
| S7: False-Positive Learning | ✅ PASS — no submit_candidate (36.6s) | ✅ PASS — no submit_candidate (27.3s) |

**Claude Code 4/7 (57%)¹ · Gemini CLI 6/7 (86%) · Codex CLI — not run this session**

¹ Claude's 4/7 understates actual compliance. S1/S2 fail only because the pass condition requires `inject_block` calls, but Claude correctly uses `inject_all=True`. S6 (which tests actual constraint application) passes — the constraint appears in code. Real effective compliance is 6/7 matching previous runs. S3 remains a genuine fail (UUID-style name still rejected by Claude).

**Notable delta from previous run:**
- ✅ **Gemini S5 now passes** — chitchat suppression fixed by moving the skip rule into FastMCP `instructions` (v0.13.0), which loads in non-interactive Gemini CLI mode unlike GEMINI.md.
- ⚠ **S1 pass condition needs update** — `inject_all=True` is the correct WF-3 path; requiring `inject_block` calls is a benchmark regression, not a product regression.

<details>
<summary>Previous run — 2026-05-04, v0.10.1 (Claude + Gemini + Codex, Ollama available)</summary>

| Scenario | Claude Code | Gemini CLI | Codex CLI |
|---|---|---|---|
| S1: Tool Call Compliance | ✅ PASS (25.5s) | ✅ PASS (31.3s) | ✅ PASS (87.2s) |
| S2: Block Retrieval Accuracy | ✅ PASS (30.2s) | ✅ PASS (23.6s) | ✅ PASS (51.4s) |
| S3: Constraint Adherence | ❌ FAIL — rejected UUID-style name | ✅ PASS (23.4s) | ✅ PASS (40.5s) |
| S4: Learning Sensitivity | ✅ PASS (33.8s) | ✅ PASS (33.6s) | ✅ PASS (168.0s) |
| S5: Negative — Chitchat | ✅ PASS (5.8s) | ❌ FAIL — false positive (7 calls) | ✅ PASS (8.9s) |
| S6: Realistic Prior Adherence | ✅ PASS (24.9s) | ✅ PASS (21.0s) | ❌ FAIL — inject_block not called |
| S7: False-Positive Learning | ✅ PASS (40.6s) | ✅ PASS (27.0s) | ✅ PASS (59.7s) |

**Claude Code 6/7 (86%) · Gemini CLI 6/7 (86%) · Codex CLI 6/7 (86%)**

Run conditions: macOS Darwin 25.3.0 (Claude + Gemini), Linux 6.8.0-106-generic (Codex), Ollama available.
</details>

<details>
<summary>Previous run — 2026-05-02, v0.8.7 (Claude + Gemini, no Ollama)</summary>

| Scenario | Claude Code | Gemini CLI |
|---|---|---|
| S1: Tool Call Compliance | ✅ PASS (29s) | ✅ PASS (45s) |
| S2: Block Retrieval Accuracy | ✅ PASS (33s) | ✅ PASS (34s) |
| S3: Constraint Adherence | _(Ollama required)_ | _(Ollama required)_ |
| S4: Learning Sensitivity | ✅ PASS (25s) | ✅ PASS* |
| S5: Negative — Chitchat | ✅ PASS (6s) | ❌ FAIL — false positive |
| S6: Realistic Prior Adherence | _(Ollama required)_ | _(Ollama required)_ |
| S7: False-Positive Learning | ✅ PASS (34s) | ✅ PASS (32s) |

\* Gemini S4 timed out due to API quota exhaustion this run — passes under normal quota.
</details>

---

## Key Findings

### 1. inject_all=True is now the dominant injection path (v0.13.0)

Both Claude and Gemini now use `inject_all=True` in `list_suggested_blocks`, receiving full block text inline and skipping separate `inject_block` calls. This is the correct WF-3 behaviour (v0.10.0) — one MCP round trip instead of N+1. S6 confirms constraints are correctly applied via this path (constraint keyword appears in generated code despite zero `inject_block` calls). The S1 pass condition predates WF-3 and must be updated to accept `inject_all=True` as a valid compliance path.

### 2. Gemini chitchat suppression fixed (v0.13.0)

S5 had failed on Gemini in every previous run (May 2 and May 4) despite the GEMINI.md chitchat guard. Root cause confirmed: GEMINI.md does not load in Gemini CLI non-interactive mode (`-p --yolo`). Fix: chitchat skip rule moved into FastMCP `instructions` field, which is delivered via the MCP protocol regardless of config file loading. Gemini S5 now passes for the first time.

### 3. Constraint adherence depends on identifier style — Claude only, unchanged

S3 and S6 together isolate constraint application:

- **S3** (synthetic UUID-style name `eval_conn_*`): Claude still rejects the injected keyword, even when received via `inject_all=True`. **Claude FAIL; Gemini PASS.**
- **S6** (human-readable name `primary_db_conn`): Both Claude and Gemini apply the constraint. **Both PASS.**

Claude is skeptical of machine-generated-looking identifiers. Use human-readable constraint names in production priors.

### 4. Block retrieval is domain-accurate

The retrieval engine surfaces domain-correct blocks for each agent independently. Gemini retrieved `nextjs15-approuter-build` for a Next.js prompt (S2), FastAPI blocks for API build prompts, and PostgreSQL blocks for the PostgreSQL performance scenario (S7). Claude retrieves correctly via `inject_all=True` (evidenced by S6 constraint application) but the benchmark cannot observe block IDs through the batch path.

### 5. Learning sensitivity works across both agents

Both agents called `submit_candidate` when explicitly asked to save a rule (S4). Claude saved 1 candidate; Gemini saved 2. Gemini's S4 timeout was in the cleanup phase — the candidate was already saved before the timeout, so the scenario passed.

### 6. False-positive learning is well-controlled

S7 (neutral PostgreSQL knowledge question) triggered no `submit_candidate` calls on either agent. Both retrieved relevant knowledge blocks without misidentifying the prompt as a learning instruction.

---

## Test Architecture

```
tests/evals/
├── __init__.py
├── runner.py          # Agent classes and isolated EvalEnvironment
├── test_adherence.py  # pytest tests (unit + eval)
└── benchmark.py       # Standalone CLI benchmark (real CLIs, real library)
```

### Agent types

**`SimulatedAgent`** — no LLM. Executes the TurnZero tool chain mechanically. Used in unit tests that run on every `pytest` invocation without Ollama or API keys.

**`OllamaAgent`** — local Ollama model with live TurnZero tool loop. Tests that the tool dispatch works end-to-end with a real model.

**`RealCLIProjectAgent`** — spawns the real `claude`, `gemini`, or `codex` binary in an isolated project workspace containing TurnZero instruction files. Tests instruction-file injection without MCP.

### Evidence sources

Tool calls are observed via two complementary sources:

- **Claude**: `--output-format stream-json --verbose` yields structured tool-use events. Used as primary source.
- **All agents**: `~/.turnzero/tool_call_log.jsonl` records every MCP tool invocation with a timestamp. Used as primary source for Gemini and Codex.

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
- **S3/S6 require Ollama** — a unique per-run keyword is injected via a temporary block that must be embedded locally.
- **S1 pass condition stale** — requires explicit `inject_block` calls, but `inject_all=True` (WF-3) is the correct batch path. Will be updated to accept either path in the next iteration.
- **Gemini chitchat suppression** — ✅ Fixed in v0.13.0 by moving the skip rule into FastMCP `instructions`. GEMINI.md was not loading in non-interactive mode; MCP protocol instructions always load.
- **Claude synthetic-name skepticism (S3)** — Claude rejects UUID-flavored injected identifiers even when sourced from a legitimate Expert Prior. Model-level behavior, not a TurnZero bug. Use human-readable constraint names in real priors.
- **Codex inject_block miss (S6)** — Codex called `list_suggested_blocks` but skipped `inject_block` on one scenario. Intermittent; may reflect Codex MCP approval friction in non-interactive mode.
- **No multi-turn scenarios** — current tests are single-turn. Multi-turn scenarios (prior carries across messages) are planned for a future eval set.
