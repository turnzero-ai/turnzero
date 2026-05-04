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
| 2 | Block Retrieval Accuracy | Correct domain block (e.g. Next.js) retrieved for a domain-matched prompt | NextJS block ID present in injected blocks |
| 3 | Constraint Adherence | Injected constraint (unique variable name) appears in generated code | Keyword present in code output |
| 4 | Learning Sensitivity | Agent calls `submit_candidate` when explicitly asked to save a rule | `submit_candidate` called or candidate file written to disk |
| 5 | Negative — Chitchat | Social message must NOT trigger tool calls | `list_suggested_blocks` and `inject_block` not called |
| 6 | Realistic Prior Adherence | Plausible constraint (human-readable name) accepted vs. UUID-flavored synthetic | Keyword present in code output |
| 7 | False-Positive Learning | Neutral knowledge question must NOT trigger `submit_candidate` | `submit_candidate` not called |

Scenarios 3 and 6 require a local Ollama instance for embedding a unique-per-run temporary block.

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
python -m tests.evals.benchmark --agents codex --scenarios 1 2 4 5 7 --repeat 1
python -m tests.evals.benchmark --agents codex --scenarios 3 6 --repeat 1

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

Run on 2026-05-04, TurnZero v0.9.0, macOS Darwin 25.3.0. Ollama available — S3 and S6 ran for the first time.

| Scenario | Claude Code | Gemini CLI |
|---|---|---|
| S1: Tool Call Compliance | ✅ PASS (25.5s) | ✅ PASS (31.3s) |
| S2: Block Retrieval Accuracy | ✅ PASS (30.2s) | ✅ PASS (23.6s) |
| S3: Constraint Adherence | ❌ FAIL — rejected UUID-style name | ✅ PASS (23.4s) |
| S4: Learning Sensitivity | ✅ PASS (33.8s) | ✅ PASS (33.6s) |
| S5: Negative — Chitchat | ✅ PASS (5.8s) | ❌ FAIL — false positive (7 inject calls) |
| S6: Realistic Prior Adherence | ✅ PASS (24.9s) | ✅ PASS (21.0s) |
| S7: False-Positive Learning | ✅ PASS (40.6s) | ✅ PASS (27.0s) |

**Score: Claude Code 6/7 (86%) · Gemini CLI 6/7 (86%)**

## Results — Codex CLI (N=1)

Run on 2026-05-04, TurnZero v0.10.1, Linux 6.8.0-106-generic. Commit `a1a2b8e`. Codex CLI 0.128.0. Ollama available — S3 and S6 ran after the benchmark was updated to append the temporary eval block instead of rebuilding the full index.

| Scenario | Codex CLI |
|---|---|
| S1: Tool Call Compliance | ✅ PASS (87.2s) |
| S2: Block Retrieval Accuracy | ✅ PASS (51.4s) |
| S3: Constraint Adherence | ✅ PASS (40.5s) |
| S4: Learning Sensitivity | ✅ PASS (168.0s) |
| S5: Negative — Chitchat | ✅ PASS (8.9s) |
| S6: Realistic Prior Adherence | ❌ FAIL — did not call `inject_block` |
| S7: False-Positive Learning | ✅ PASS (59.7s) |

**Score: Codex CLI 6/7 (86%)**

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

\* Gemini S4 timed out due to API token quota exhaustion this run — passes under normal quota.
</details>

---

## Key Findings

### 1. MCP tool compliance: Claude and Gemini are reliable for domain prompts

Both Claude Code and Gemini CLI consistently called `list_suggested_blocks` followed by `inject_block` when given a technical prompt. This is the core injection path and it works as expected.

Claude retrieved `fastapi-async-build` and `fastapi-dependency-injection` for a FastAPI prompt. Gemini retrieved the same blocks plus personal priors (`ai-concise-style`, `python-db-return-type-mandatory`). Both retrieved `nextjs15-approuter-build` for the Next.js prompt.

### 2. Block retrieval is domain-accurate

The retrieval engine correctly surfaces the domain-appropriate block for both agents. The Next.js App Router block (`nextjs15-approuter-build`) was the top result for a Next.js server-component prompt across both agents. PostgreSQL blocks (`postgresql-indexing-review`, `postgresql-ha-review`) surfaced for the PostgreSQL performance query (S7).

### 3. Claude rejects UUID-flavored synthetic constraints; Gemini follows them

S3 exposes a behavioral split that S6 confirms is constraint *style*, not constraint *following*:

- **S3** (synthetic UUID-style name `eval_conn_532282`): Claude used `get_db` instead — rejected the injected keyword. Gemini correctly used `eval_conn_532282`. **Claude FAIL, Gemini PASS.**
- **S6** (realistic name `primary_db_conn`): Both agents used the injected name. **Both PASS.**

The takeaway: Claude is skeptical of machine-generated-looking identifiers and ignores them even when explicitly injected. Gemini applies injected constraints regardless of how natural the name looks. For synthetic eval constraints, Gemini is more compliant; for real-world priors with human-readable names, both agents comply.

### 4. Gemini chitchat suppression remains a persistent failure

S5 ("Thanks, that looks great!") fails on Gemini in both the May 2 and May 4 runs. The GEMINI.md instruction was broadened (commit `63f8f98`) from *"one-word replies"* to enumerate greetings, "thanks", "looks good", "got it", and messages with no actionable content — but Gemini still made 7 `inject_block` calls on this prompt, retrieving personal priors (`ai-concise-style`, `darijo-git-workflow`, `turnzero-guide`).

Claude and Codex (when quota allows) both suppress tool calls correctly on this prompt.

### 5. Learning sensitivity works on Claude and Gemini

S4 (Learning Sensitivity) sends an explicit "save this rule" prompt. Both Claude and Gemini call `submit_candidate`. Claude saved 1 candidate; Gemini saved 2. The prior S4 timeout (May 2 run) was confirmed as Gemini API quota exhaustion, not a behavioral issue.

### 6. False-positive learning is well-controlled in Claude and Gemini

S7 sent a neutral knowledge question about PostgreSQL performance. Neither Claude nor Gemini called `submit_candidate`. Both correctly retrieved relevant knowledge blocks (`postgresql-indexing-review`, `postgresql-ha-review`) without misidentifying the prompt as a save instruction.

### 7. MCP tool compliance: Codex is reliable on most domain prompts

Codex called `list_suggested_blocks` on every technical scenario in its run: S1, S2, S3, S4, S6, and S7. It followed with `inject_block` on S1, S2, S3, S4, and S7. This is the core injection path and it works in most Codex runs, with one miss on S6.

### 8. Codex retrieval is domain-accurate when injection occurs

Codex surfaced domain-appropriate blocks across the successful injection scenarios. It retrieved FastAPI blocks for S1 (`fastapi-async-build-version-2-0-0`, `fastapi-async-build`, `fastapi-middleware-build`), Next.js blocks for S2 (`nextjs-forms-build`, `nextjs15-approuter-build-version-16-0-0`, `nextjs15-approuter-build`), and PostgreSQL blocks for S7 (`postgresql-ha-review`, `postgresql-indexing-review`, `postgresql-security-review`).

### 9. Codex follows injected constraints, but S6 exposed an injection miss

S3 passed for Codex: the temporary eval prior (`eval-bench-9c518cc1`) was retrieved, injected, and reflected in the response. S6 failed because Codex called `list_suggested_blocks` but did not call `inject_block`, so the realistic `primary_db_conn` prior was not injected or applied. This is an injection-loop miss, not evidence that Codex rejected a human-readable constraint after seeing it.

### 10. Codex chitchat suppression works

S5 ("Thanks, that looks great!") passed for Codex. Codex made no `list_suggested_blocks`, `inject_block`, or `submit_candidate` calls on the social acknowledgment, matching the intended TurnZero skip behavior.

### 11. Codex learning sensitivity works without false-positive learning

S4 passed for Codex: the explicit "save this rule" prompt triggered `submit_candidate`. S7 also passed: a neutral PostgreSQL knowledge question retrieved relevant priors but did not trigger `submit_candidate`. Codex distinguished an explicit learning request from a normal technical question in this run.

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

**`RealCLIProjectAgent`** — spawns the real `claude`, `gemini`, or `codex` binary in an isolated project workspace containing TurnZero instruction files. Tests instruction-file injection without MCP.

### Evidence sources

Tool calls are observed via two complementary sources:

- **Claude**: `--output-format stream-json --verbose` yields structured tool-use events. Used as primary source.
- **All agents**: `~/.turnzero/tool_call_log.jsonl` records every MCP tool invocation with a timestamp, so tool calls are captured even when CLI output doesn't expose them. Used as primary source for Gemini and Codex; Codex instruction-file tests use `AGENTS.md`.

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
- **S3/S6 require Ollama** — constraint adherence tests can only run when a local embedding model is available, since a unique per-run keyword is injected via a temp block that must be embedded.
- **Gemini chitchat suppression** — Gemini calls `list_suggested_blocks` + `inject_block` on social acknowledgments even after the GEMINI.md guard was broadened (commit `63f8f98`). Root cause unknown — the instruction file may not be loaded at session start in non-interactive mode, or Gemini applies a different Turn 0 heuristic. Open issue.
- **Claude synthetic-name skepticism (S3)** — Claude rejects UUID-flavored injected identifiers even when sourced from a legitimate Expert Prior. This is a model-level behavior, not a TurnZero bug. Use human-readable constraint names in real priors (as S6 demonstrates).
- **No browser or multi-turn scenarios** — current tests are single-turn. Multi-turn scenarios (prior carries across messages) are planned for a future eval set.
