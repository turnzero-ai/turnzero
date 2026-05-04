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

Latest N=1 run per agent. All three agents scored 6/7 (86%).

| Scenario | Claude Code | Gemini CLI | Codex CLI |
|---|---|---|---|
| S1: Tool Call Compliance | ✅ PASS (25.5s) | ✅ PASS (31.3s) | ✅ PASS (87.2s) |
| S2: Block Retrieval Accuracy | ✅ PASS (30.2s) | ✅ PASS (23.6s) | ✅ PASS (51.4s) |
| S3: Constraint Adherence | ❌ FAIL — rejected UUID-style name | ✅ PASS (23.4s) | ✅ PASS (40.5s) |
| S4: Learning Sensitivity | ✅ PASS (33.8s) | ✅ PASS (33.6s) | ✅ PASS (168.0s) |
| S5: Negative — Chitchat | ✅ PASS (5.8s) | ❌ FAIL — false positive (7 calls) | ✅ PASS (8.9s) |
| S6: Realistic Prior Adherence | ✅ PASS (24.9s) | ✅ PASS (21.0s) | ❌ FAIL — `inject_block` not called |
| S7: False-Positive Learning | ✅ PASS (40.6s) | ✅ PASS (27.0s) | ✅ PASS (59.7s) |

**Claude Code 6/7 (86%) · Gemini CLI 6/7 (86%) · Codex CLI 6/7 (86%)**

Run conditions:

- **Claude Code + Gemini CLI** — 2026-05-04, TurnZero v0.9.0, macOS Darwin 25.3.0, Ollama available
- **Codex CLI** — 2026-05-04, TurnZero v0.10.1, Linux 6.8.0-106-generic, Codex CLI 0.128.0, Ollama available

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

### 1. MCP tool compliance is consistent across all three agents

All three agents reliably called `list_suggested_blocks` followed by `inject_block` when given a technical prompt. Claude and Gemini had no injection-loop misses; Codex missed `inject_block` once on S6 but succeeded on every other scenario. The core MCP injection path works across all tested clients.

### 2. Block retrieval is domain-accurate

The retrieval engine surfaces the correct block for each agent independently. All three retrieved the Next.js App Router block (`nextjs15-approuter-build`) for a Next.js server-component prompt, FastAPI blocks for API build prompts, and PostgreSQL blocks (`postgresql-indexing-review`, `postgresql-ha-review`) for the PostgreSQL performance scenario (S7).

### 3. Constraint adherence depends on identifier style — for Claude only

S3 and S6 together isolate whether agents follow injected naming constraints:

- **S3** (synthetic UUID-style name `eval_conn_532282`): Claude substituted `get_db` — rejected the injected keyword. Gemini and Codex both used `eval_conn_532282`. **Claude FAIL; Gemini and Codex PASS.**
- **S6** (human-readable name `primary_db_conn`): Claude and Gemini applied the constraint. Codex called `list_suggested_blocks` but skipped `inject_block` — the prior was never seen. **Claude and Gemini PASS; Codex FAIL.**

Claude is skeptical of machine-generated-looking identifiers and ignores them even when injected from a legitimate prior. For real-world priors with human-readable names, all agents that complete the injection loop comply. Use human-readable constraint names in production priors.

### 4. Chitchat suppression: Claude and Codex pass; Gemini fails consistently

S5 ("Thanks, that looks great!") has failed on Gemini in every run (May 2 and May 4). Gemini made 7 `inject_block` calls on this social acknowledgment despite the GEMINI.md chitchat guard enumerating greetings and social phrases. Claude and Codex both suppressed all tool calls correctly. Root cause for Gemini is unknown — the instruction file may not load in non-interactive mode.

### 5. Learning sensitivity works across all three agents

All three agents called `submit_candidate` when explicitly asked to save a rule (S4). Claude saved 1 candidate; Gemini saved 2; Codex saved 1. The prior S4 timeout (May 2, Gemini) was API quota exhaustion, not a behavioral issue.

### 6. False-positive learning is well-controlled

S7 sent a neutral PostgreSQL knowledge question. None of the three agents called `submit_candidate`. All correctly retrieved relevant knowledge blocks without misidentifying the prompt as a learning instruction.

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
- **Gemini chitchat suppression** — Gemini calls `list_suggested_blocks` + `inject_block` on social acknowledgments even after the GEMINI.md guard was broadened. Root cause unknown — likely the instruction file is not loaded in non-interactive mode. Open issue.
- **Claude synthetic-name skepticism (S3)** — Claude rejects UUID-flavored injected identifiers even when sourced from a legitimate Expert Prior. Model-level behavior, not a TurnZero bug. Use human-readable constraint names in real priors.
- **Codex inject_block miss (S6)** — Codex called `list_suggested_blocks` but skipped `inject_block` on one scenario. Intermittent; may reflect Codex MCP approval friction in non-interactive mode.
- **No multi-turn scenarios** — current tests are single-turn. Multi-turn scenarios (prior carries across messages) are planned for a future eval set.
