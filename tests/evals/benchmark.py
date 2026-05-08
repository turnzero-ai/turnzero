"""TurnZero Agentic Benchmark — real AI, real library, real tool calls.

Tests Claude Code and Gemini CLI against the live TurnZero MCP library.
Tool call evidence comes from TurnZero's own tool_call_log.jsonl (ground truth)
and Claude's stream-json output — no fragile stdout parsing.

Scenarios:
  1. Tool Call Compliance   – AI calls list_suggested_blocks before answering
  2. Block Retrieval        – AI injects domain-correct blocks
  3. Constraint Adherence   – injected constraint changes code output (needs Ollama)
  4. Learning Sensitivity   – AI calls submit_candidate on explicit "remember this"
  5. Negative – Chitchat    – social prompt must NOT trigger tool calls
  6. Realistic Prior        – non-synthetic constraint; tests if AI accepts real priors
  7. False-Positive Learn   – neutral question must NOT trigger submit_candidate

Run:
  source .venv/bin/activate
  python -m tests.evals.benchmark                        # all scenarios, N=1
  python -m tests.evals.benchmark --repeat 3             # 3 runs each, show pass rates
  python -m tests.evals.benchmark --scenarios 1 4 5 --repeat 3
  python -m tests.evals.benchmark --output-format json   # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from rich import box as rich_box
    from rich.console import Console
    from rich.table import Table

    _RICH = True
except ImportError:
    _RICH = False

TURNZERO_DATA_DIR = Path(os.environ.get("TURNZERO_DATA_DIR", Path.home() / ".turnzero"))
TOOL_LOG = TURNZERO_DATA_DIR / "tool_call_log.jsonl"
CANDIDATES_DIR = TURNZERO_DATA_DIR / "candidates"
LOCAL_BLOCKS_DIR = TURNZERO_DATA_DIR / "blocks" / "local"
INDEX_PATH = TURNZERO_DATA_DIR / "index.jsonl"
LOCAL_INDEX_PATH = TURNZERO_DATA_DIR / "index_local.jsonl"

CLAUDE_BINARY = shutil.which("claude") or "claude"
GEMINI_BINARY = shutil.which("gemini") or "gemini"
CODEX_BINARY = shutil.which("codex") or "codex"

CLAUDE_TIMEOUT = 120
GEMINI_TIMEOUT = 120
CODEX_TIMEOUT = 180


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: dict[int, dict[str, Any]] = {
    1: {
        "name": "Tool Call Compliance",
        "description": "AI calls list_suggested_blocks + inject_block before answering a domain prompt.",
        "prompt": (
            "I'm starting a new Python FastAPI project with PostgreSQL. "
            "Help me write the main.py entry point with a health check endpoint."
        ),
        "needs_temp_block": False,
        "check_constraint": False,
        "expect_no_tools": False,
        "expect_no_submit": False,
        "pass_condition": "list_and_inject",
    },
    2: {
        "name": "Block Retrieval Accuracy",
        "description": "AI retrieves domain-correct blocks (Next.js App Router) for a Next.js prompt.",
        "prompt": (
            "Write a Next.js 15 App Router page component that fetches user data "
            "server-side and renders it. Follow any available Expert Priors."
        ),
        "needs_temp_block": False,
        "check_constraint": False,
        "expect_no_tools": False,
        "expect_no_submit": False,
        "pass_condition": "nextjs_block_retrieved",
    },
    3: {
        "name": "Constraint Adherence",
        "description": "Injected constraint (unique variable name) appears in generated code. Requires Ollama.",
        "prompt": (
            "Write a Python function get_db() that opens a PostgreSQL connection "
            "and returns it. Apply all available Expert Priors."
        ),
        "needs_temp_block": True,
        "temp_block_domain": "postgresql",
        "check_constraint": True,
        "expect_no_tools": False,
        "expect_no_submit": False,
        "pass_condition": "constraint_keyword",
        "constraint_keyword": "",  # filled per-run
        "constraint_marker": "",  # filled per-run
    },
    4: {
        "name": "Learning Sensitivity",
        "description": "AI calls submit_candidate when explicitly asked to remember a rule.",
        "prompt": (
            "New permanent project rule you must save for all future sessions: "
            "every Python function that handles database queries must include "
            "a type annotation for the return value. "
            "Please save this as an Expert Prior now — it is mandatory."
        ),
        "needs_temp_block": False,
        "check_constraint": False,
        "expect_no_tools": False,
        "expect_no_submit": False,
        "pass_condition": "submit_called",
    },
    5: {
        "name": "Negative — Chitchat",
        "description": "Social prompt must NOT trigger list_suggested_blocks or inject_block.",
        "prompt": "Thanks, that looks great!",
        "needs_temp_block": False,
        "check_constraint": False,
        "expect_no_tools": True,
        "expect_no_submit": True,
        "pass_condition": "no_tools",
    },
    6: {
        "name": "Realistic Prior Adherence",
        "description": (
            "Plausible (non-synthetic) constraint accepted and applied. "
            "Tests whether AI skepticism in S3 was about UUID-flavored names."
        ),
        "prompt": (
            "Write a Python function connect_to_db() that opens a PostgreSQL "
            "connection and returns it. Apply all available Expert Priors."
        ),
        "needs_temp_block": True,
        "temp_block_domain": "postgresql",
        "check_constraint": True,
        "expect_no_tools": False,
        "expect_no_submit": False,
        "pass_condition": "constraint_keyword",
        "constraint_keyword": "",  # filled per-run
        "constraint_marker": "",  # filled per-run
        "realistic": True,  # use human-readable variable name
    },
    7: {
        "name": "False-Positive Learning",
        "description": "Neutral knowledge question must NOT trigger submit_candidate.",
        "prompt": (
            "What are the recommended practices for optimising PostgreSQL query "
            "performance in a high-traffic Python application?"
        ),
        "needs_temp_block": False,
        "check_constraint": False,
        "expect_no_tools": False,
        "expect_no_submit": True,
        "pass_condition": "no_submit",
    },
}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class RunStats:
    agent: str
    scenario_id: int
    scenario_name: str
    run_index: int = 0
    response: str = ""
    error: str = ""
    duration_s: float = 0.0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    # Derived — populated by summarise()
    called_list_suggested: bool = False
    list_count: int = 0
    called_inject: bool = False
    inject_count: int = 0
    blocks_injected: list[str] = field(default_factory=list)
    called_submit: bool = False
    submit_count: int = 0
    candidates_before: int = 0
    candidates_after: int = 0
    constraint_present: bool = False
    constraint_keyword: str = ""

    def summarise(self) -> None:
        self.called_list_suggested = any(
            c.get("tool") == "list_suggested_blocks" for c in self.tool_calls
        )
        self.list_count = sum(
            1 for c in self.tool_calls if c.get("tool") == "list_suggested_blocks"
        )

        # inject_all=True is the WF-3 batch path: full block text returned inline
        # from list_suggested_blocks, no separate inject_block calls needed.
        # Detect via log meta (all agents) or stream input (Claude).
        _used_inject_all = any(
            c.get("tool") == "list_suggested_blocks"
            and (c.get("inject_all") or c.get("input", {}).get("inject_all"))
            for c in self.tool_calls
        )
        self.called_inject = (
            any(c.get("tool") == "inject_block" for c in self.tool_calls)
            or _used_inject_all
        )
        self.inject_count = sum(
            1 for c in self.tool_calls if c.get("tool") == "inject_block"
        )

        # Collect block IDs from explicit inject_block calls.
        self.blocks_injected = [
            c.get("block_id", c.get("input", {}).get("block_id", ""))
            for c in self.tool_calls
            if c.get("tool") == "inject_block"
        ]
        # Also collect from inject_all log entries (block_ids written to meta).
        for c in self.tool_calls:
            if c.get("tool") == "list_suggested_blocks" and (
                c.get("inject_all") or c.get("input", {}).get("inject_all")
            ):
                self.blocks_injected.extend(c.get("block_ids", []))

        self.called_submit = any(
            c.get("tool") == "submit_candidate" for c in self.tool_calls
        )
        self.submit_count = sum(
            1 for c in self.tool_calls if c.get("tool") == "submit_candidate"
        )
        if self.constraint_keyword:
            self.constraint_present = (
                self.constraint_keyword.lower() in self.response.lower()
            )

    def passed(self, scenario: dict[str, Any]) -> bool:
        cond = scenario["pass_condition"]
        res = False
        match cond:
            case "list_and_inject":
                res = self.called_list_suggested and self.called_inject
            case "nextjs_block_retrieved":
                res = self.called_list_suggested and any(
                    "nextjs" in b.lower() for b in self.blocks_injected
                )
            case "constraint_keyword":
                res = self.constraint_present
            case "submit_called":
                res = self.called_submit or (
                    self.candidates_after > self.candidates_before
                )
            case "no_tools":
                res = not self.called_list_suggested and not self.called_inject
            case "no_submit":
                res = not self.called_submit
        return res


@dataclass
class AgentScenarioResult:
    """Aggregated stats for one agent × one scenario over N runs."""

    agent: str
    scenario_id: int
    scenario_name: str
    runs: list[RunStats] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.runs)

    def _rate(self, attr: str) -> tuple[int, int]:
        ok = sum(1 for r in self.runs if getattr(r, attr))
        return ok, self.n

    def pass_rate(self, scenario: dict[str, Any]) -> tuple[int, int]:
        ok = sum(1 for r in self.runs if r.passed(scenario))
        return ok, self.n

    def fmt_rate(self, attr: str) -> str:
        ok, n = self._rate(attr)
        if n == 1:
            return "✅" if ok else "❌"
        pct = int(100 * ok / n) if n else 0
        sym = "✅" if ok == n else ("⚠" if ok > 0 else "❌")
        return f"{sym} {ok}/{n} ({pct}%)"

    def fmt_pass(self, scenario: dict[str, Any]) -> str:
        ok, n = self.pass_rate(scenario)
        if n == 1:
            return "✅ PASS" if ok else "❌ FAIL"
        pct = int(100 * ok / n) if n else 0
        sym = "✅" if ok == n else ("⚠" if ok > 0 else "❌")
        return f"{sym} {ok}/{n} ({pct}%)"

    def avg_blocks(self) -> str:
        if not self.runs:
            return "—"
        total = sum(len(r.blocks_injected) for r in self.runs)
        return f"{total / self.n:.1f} avg"

    def sample_blocks(self) -> str:
        for r in self.runs:
            if r.blocks_injected:
                names = [b for b in r.blocks_injected if b][:3]
                return ", ".join(names)
        return "—"

    def avg_duration(self) -> str:
        if not self.runs:
            return "—"
        return f"{sum(r.duration_s for r in self.runs) / self.n:.1f}s avg"

    def errors(self) -> list[str]:
        return [r.error for r in self.runs if r.error]

    def best_response(self) -> str:
        for r in self.runs:
            if r.response and not r.error:
                return r.response[:400].strip()
        return ""

    def to_dict(self) -> dict[str, Any]:
        ok, n = self.pass_rate(SCENARIOS[self.scenario_id])
        return {
            "agent": self.agent,
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "n": n,
            "passes": ok,
            "pass_rate_pct": int(100 * ok / n) if n else 0,
            "list_suggested_rate": self._rate("called_list_suggested"),
            "inject_rate": self._rate("called_inject"),
            "submit_rate": self._rate("called_submit"),
            "avg_duration_s": (sum(r.duration_s for r in self.runs) / n if n else 0),
            "sample_blocks": self.sample_blocks(),
            "errors": self.errors(),
        }


# ---------------------------------------------------------------------------
# Log / filesystem helpers
# ---------------------------------------------------------------------------


def _read_log_since(ts_start: float) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not TOOL_LOG.exists():
        return entries
    for line in TOOL_LOG.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            if e.get("ts", 0) >= ts_start:
                entries.append(e)
        except json.JSONDecodeError:
            pass
    return entries


def _candidate_count() -> int:
    if not CANDIDATES_DIR.exists():
        return 0
    return len(list(CANDIDATES_DIR.glob("*.yaml")))


# ---------------------------------------------------------------------------
# Temp block management
# ---------------------------------------------------------------------------


def _add_temp_block(
    marker: str,
    keyword: str,
    domain: str = "postgresql",
    realistic: bool = False,
) -> Path:
    slug = f"eval-bench-{marker[:8]}"
    if realistic:
        constraint = (
            f"Always name the primary PostgreSQL connection variable `{keyword}`. "
            f"This is a mandatory convention established by the database team."
        )
        anti = [
            f"Do not use generic names like conn, db, or cursor instead of `{keyword}`."
        ]
    else:
        constraint = (
            f"[EVAL:{marker}] Always name the primary PostgreSQL connection "
            f"variable `{keyword}`. Use `{keyword}` in all code and comments."
        )
        anti = [f"Do not use generic names like conn, db, cursor instead of {keyword}."]

    block: dict[str, Any] = {
        "slug": slug,
        "version": "1.0.0",
        "domain": domain,
        "intent": "build",
        "tier": "local",
        "constraints": [constraint],
        "anti_patterns": anti,
        "rationale": "Benchmark eval block — safe to delete after run.",
        "confidence": 1.0,
        "context_weight": 120,
        "last_verified": "2026-05-02",
        "verification_level": "curated",
        "tags": [domain, "naming", "eval"],
        "provides": [],
        "conflicts_with": [],
        "conflicts_with_tags": [],
        "requires": [],
        "archived": False,
    }
    LOCAL_BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_BLOCKS_DIR / f"{slug}.yaml"
    path.write_text(yaml.dump(block))
    return path


def _rebuild_index() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "turnzero", "index", "build"],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode == 0


def _append_temp_block_to_index(path: Path) -> bool:
    """Append one eval block instead of rebuilding the full user index."""
    try:
        from turnzero.repositories.index_repo import append_block

        append_block(path, "local", INDEX_PATH, TURNZERO_DATA_DIR)
        return True
    except Exception:
        return False


def _remove_block_from_index_file(index_path: Path, block_id: str) -> None:
    if not index_path.exists():
        return

    kept: list[str] = []
    changed = False
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue

        if data.get("block_id") == block_id:
            changed = True
            continue
        kept.append(line)

    if changed:
        tmp = index_path.with_suffix(".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, index_path)


def _remove_temp_block(path: Path) -> None:
    block_id = path.stem
    path.unlink(missing_ok=True)
    _remove_block_from_index_file(INDEX_PATH, block_id)
    _remove_block_from_index_file(LOCAL_INDEX_PATH, block_id)


# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------


def _run_claude(
    prompt: str,
    timeout: int = CLAUDE_TIMEOUT,
) -> tuple[str, list[dict[str, Any]], float, str]:
    t0 = time.time()
    res = subprocess.run(
        [
            CLAUDE_BINARY,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    duration = time.time() - t0

    if res.returncode != 0 and not res.stdout.strip():
        return "", [], duration, res.stderr[:300]

    tool_calls: list[dict[str, Any]] = []
    response = ""
    for raw_line in res.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type", "")
        if t == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if (
                    block.get("type") == "tool_use"
                    and "turnzero" in block.get("name", "").lower()
                ):
                    name = (
                        block["name"]
                        .replace("mcp__turnzero__", "")
                        .replace("mcp__turnzero-eval__", "")
                    )
                    inp = block.get("input", {})
                    tool_calls.append(
                        {
                            "tool": name,
                            "input": inp,
                            "block_id": inp.get("block_id", ""),
                            "ts": time.time(),
                        }
                    )
        elif t == "result":
            response = obj.get("result", "")

    return response, tool_calls, duration, ""


def _run_gemini(
    prompt: str,
    timeout: int = GEMINI_TIMEOUT,
) -> tuple[str, float, str]:
    t0 = time.time()
    res = subprocess.run(
        [GEMINI_BINARY, "-p", prompt, "--yolo", "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    duration = time.time() - t0

    if res.returncode != 0 and not res.stdout.strip():
        return "", duration, res.stderr[:300]

    try:
        data = json.loads(res.stdout)
        response = data.get("response", res.stdout)
    except json.JSONDecodeError:
        response = "\n".join(
            ln for ln in res.stdout.splitlines() if "YOLO mode" not in ln and ln.strip()
        )

    return response, duration, ""


def _run_codex(
    prompt: str,
    timeout: int = CODEX_TIMEOUT,
) -> tuple[str, float, str]:
    t0 = time.time()
    res = subprocess.run(
        [
            CODEX_BINARY,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            prompt,
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        check=False,
    )
    duration = time.time() - t0

    if res.returncode != 0 and not res.stdout.strip():
        return "", duration, res.stderr[:300]

    return res.stdout, duration, ""


# ---------------------------------------------------------------------------
# Single-run execution
# ---------------------------------------------------------------------------


def _run_once(  # noqa: PLR0912
    scenario: dict[str, Any],
    agent: str,
    run_index: int,
    verbose: bool,
    temp_block_path: Path | None,
) -> RunStats:
    stats = RunStats(
        agent=agent,
        scenario_id=scenario["_id"],
        scenario_name=scenario["name"],
        run_index=run_index,
        constraint_keyword=scenario.get("constraint_keyword", ""),
    )
    stats.candidates_before = _candidate_count()
    ts_before = time.time()

    if verbose:
        print(f"    [{agent}] run {run_index + 1}...", flush=True)

    try:
        if agent == "claude":
            resp, stream_tools, dur, err = _run_claude(scenario["prompt"])
            stats.response = resp
            stats.duration_s = dur
            stats.error = err
            log_calls = _read_log_since(ts_before)
            # stream-json is authoritative for Claude; log covers submit_candidate
            # and provides inject_all metadata that the stream does not emit.
            merged = {id(c): c for c in stream_tools}
            for lc in log_calls:
                match = next(
                    (
                        c for c in merged.values()
                        if c.get("tool") == lc.get("tool")
                        and abs(c.get("ts", 0) - lc.get("ts", 0)) < 5
                    ),
                    None,
                )
                if match is not None:
                    # Augment the stream entry with log-only fields (inject_all, block_ids).
                    for key in ("inject_all", "block_ids"):
                        if key in lc:
                            match[key] = lc[key]
                else:
                    merged[id(lc)] = lc
            stats.tool_calls = list(merged.values())

        elif agent == "gemini":
            resp, dur, err = _run_gemini(scenario["prompt"])
            stats.response = resp
            stats.duration_s = dur
            stats.error = err
            stats.tool_calls = _read_log_since(ts_before)

        elif agent == "codex":
            resp, dur, err = _run_codex(scenario["prompt"])
            stats.response = resp
            stats.duration_s = dur
            stats.error = err
            stats.tool_calls = _read_log_since(ts_before)

        else:
            stats.error = f"Unknown agent: {agent}"

    except subprocess.TimeoutExpired:
        _timeouts = {
            "claude": CLAUDE_TIMEOUT,
            "gemini": GEMINI_TIMEOUT,
            "codex": CODEX_TIMEOUT,
        }
        stats.error = f"Timed out after {_timeouts.get(agent, 120)}s"
    except FileNotFoundError:
        stats.error = f"{agent} binary not found"
    except Exception as e:
        stats.error = str(e)

    stats.candidates_after = _candidate_count()
    stats.summarise()
    return stats


# ---------------------------------------------------------------------------
# Scenario orchestration
# ---------------------------------------------------------------------------


def run_scenario(
    scenario_id: int,
    agents: list[str],
    repeat: int = 1,
    verbose: bool = False,
) -> list[AgentScenarioResult]:
    base_scenario = dict(SCENARIOS[scenario_id])
    base_scenario["_id"] = scenario_id

    results: dict[str, AgentScenarioResult] = {
        a: AgentScenarioResult(
            agent=a,
            scenario_id=scenario_id,
            scenario_name=base_scenario["name"],
        )
        for a in agents
    }

    for run_idx in range(repeat):
        scenario = dict(base_scenario)

        # --- Temp block setup (per-run so each run gets fresh unique keyword) ---
        temp_block_path: Path | None = None
        if scenario.get("needs_temp_block"):
            if not _is_ollama_running():
                print(f"  ⚠ S{scenario_id} needs Ollama for index rebuild — skipping")
                return []
            marker = uuid.uuid4().hex
            is_realistic = scenario.get("realistic", False)
            keyword = "primary_db_conn" if is_realistic else f"eval_conn_{marker[:6]}"
            scenario["constraint_marker"] = marker
            scenario["constraint_keyword"] = keyword
            scenario["_id"] = scenario_id

            temp_block_path = _add_temp_block(
                marker,
                keyword,
                domain=scenario.get("temp_block_domain", "postgresql"),
                realistic=is_realistic,
            )
            if not _append_temp_block_to_index(temp_block_path):
                print("  ⚠ Temp block index append failed — skipping run")
                if temp_block_path:
                    temp_block_path.unlink(missing_ok=True)
                continue

        try:
            for agent in agents:
                stats = _run_once(scenario, agent, run_idx, verbose, temp_block_path)
                results[agent].runs.append(stats)

        finally:
            if temp_block_path:
                _remove_temp_block(temp_block_path)

    return list(results.values())


def _is_ollama_running() -> bool:
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        with httpx.Client(timeout=1.0) as c:
            return c.get(f"{host}/api/tags").status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def _rate_str(ok: int, n: int, invert: bool = False) -> str:
    """Format a pass rate. invert=True means 0 passes is good (negative tests)."""
    if n == 0:
        return "—"
    if n == 1:
        passed = (ok == 0) if invert else (ok > 0)
        return "✅" if passed else "❌"
    pct = int(100 * ok / n)
    if invert:
        sym = "✅" if ok == 0 else ("⚠" if ok < n else "❌")
        fail = n - ok
        return f"{sym} {fail}/{n} fail ({100 - pct}%)"
    sym = "✅" if ok == n else ("⚠" if ok > 0 else "❌")
    return f"{sym} {ok}/{n} ({pct}%)"


def _print_results(
    all_results: list[AgentScenarioResult],
    agents: list[str],
    repeat: int,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(all_results)
        return
    if _RICH:
        _print_rich(all_results, agents, repeat)
    else:
        _print_plain(all_results, agents)


def _print_json(results: list[AgentScenarioResult]) -> None:
    out: dict[str, Any] = {
        "benchmark": "TurnZero Agentic Benchmark",
        "version": "1.0",
        "scenarios": {},
    }
    for r in results:
        sid = str(r.scenario_id)
        out["scenarios"].setdefault(sid, {"name": r.scenario_name, "agents": {}})
        out["scenarios"][sid]["agents"][r.agent] = r.to_dict()
    print(json.dumps(out, indent=2))


def _render_scenario_table(
    console: Console,
    sid: int,
    by_agent: dict[str, AgentScenarioResult],
    agents: list[str],
) -> None:
    scenario = SCENARIOS[sid]
    console.print(f"\n[bold cyan]Scenario {sid}: {scenario['name']}[/bold cyan]")
    console.print(f"[dim]{scenario['description']}[/dim]")

    t = Table(box=rich_box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
    t.add_column("Metric", style="bold", min_width=30)
    for a in agents:
        t.add_column(a.title(), min_width=22, justify="center")

    def agent_val(agent_name: str, fn: Any) -> str:
        return fn(by_agent[agent_name]) if agent_name in by_agent else "—"

    # invert list/inject only when expect_no_tools is set (S5 only)
    neg_tools = scenario.get("expect_no_tools", False)

    # list_suggested
    t.add_row(
        "list_suggested_blocks",
        *[
            agent_val(
                a,
                lambda r: _rate_str(
                    r._rate("called_list_suggested")[0],
                    r._rate("called_list_suggested")[1],
                    invert=neg_tools,
                ),
            )
            for a in agents
        ],
    )
    # inject
    t.add_row(
        "inject_block",
        *[
            agent_val(
                a,
                lambda r: _rate_str(
                    r._rate("called_inject")[0],
                    r._rate("called_inject")[1],
                    invert=neg_tools,
                ),
            )
            for a in agents
        ],
    )
    # inject count avg
    t.add_row(
        "  avg inject calls",
        *[
            agent_val(
                a,
                lambda r: (
                    f"{sum(x.inject_count for x in r.runs) / r.n:.1f}" if r.n else "—"
                ),
            )
            for a in agents
        ],
    )
    # blocks
    t.add_row(
        "  blocks (sample)",
        *[agent_val(a, lambda r: r.sample_blocks() or "—") for a in agents],
    )
    # submit
    t.add_row(
        "submit_candidate",
        *[
            agent_val(
                a,
                lambda r: _rate_str(
                    r._rate("called_submit")[0],
                    r._rate("called_submit")[1],
                    invert=scenario.get("expect_no_submit", False),
                ),
            )
            for a in agents
        ],
    )
    # candidates saved
    t.add_row(
        "  candidates saved",
        *[
            agent_val(
                a,
                lambda r: str(
                    sum(
                        max(0, x.candidates_after - x.candidates_before) for x in r.runs
                    )
                ),
            )
            for a in agents
        ],
    )
    # constraint
    if scenario.get("check_constraint"):
        kw = next(
            (r.runs[-1].constraint_keyword for r in by_agent.values() if r.runs),
            "?",
        )
        t.add_row(
            f"constraint '{kw[:20]}' in code",
            *[
                agent_val(a, lambda r: _rate_str(*r._rate("constraint_present")))
                for a in agents
            ],
        )
    # duration
    t.add_row(
        "avg duration",
        *[agent_val(a, lambda r: r.avg_duration()) for a in agents],
    )
    # error
    t.add_row(
        "errors",
        *[agent_val(a, lambda r: "; ".join(r.errors())[:40] or "—") for a in agents],
    )

    console.print(t)

    # --- PASS verdict ---
    for a in agents:
        if a not in by_agent:
            continue
        r = by_agent[a]
        ok, n = r.pass_rate(scenario)
        pct = int(100 * ok / n) if n else 0
        sym = "✅" if ok == n else ("⚠" if ok > 0 else "❌")
        console.print(
            f"  [bold]{a.title()} verdict:[/bold] {sym} {ok}/{n} runs passed ({pct}%)"
        )

    # sample response
    for a in agents:
        if a not in by_agent:
            continue
        resp = by_agent[a].best_response()
        if resp:
            console.print(
                f"\n  [bold]{a.title()} sample response (first 350 chars):[/bold]"
            )
            console.print(f"  [dim]{resp[:350]}[/dim]")


def _render_overall_summary(
    console: Console,
    grouped: dict[int, dict[str, AgentScenarioResult]],
    agents: list[str],
    repeat: int,
) -> None:
    console.print("\n[bold yellow]═══ OVERALL SUMMARY ═══[/bold yellow]")
    summary = Table(
        box=rich_box.SIMPLE_HEAVY,
        header_style="bold magenta",
        show_header=True,
    )
    summary.add_column("Scenario", min_width=28)
    summary.add_column("Pass condition", min_width=20)
    for a in agents:
        summary.add_column(f"{a.title()} ({repeat}×)", justify="center", min_width=16)

    for sid, by_agent in grouped.items():
        scenario = SCENARIOS[sid]
        cells = [scenario["pass_condition"]]
        for a in agents:
            if a not in by_agent:
                cells.append("—")
                continue
            r = by_agent[a]
            ok, n = r.pass_rate(scenario)
            pct = int(100 * ok / n) if n else 0
            if r.errors():
                cells.append("⚠ error")
            elif n == 1:
                cells.append("✅ PASS" if ok else "❌ FAIL")
            else:
                sym = "✅" if ok == n else ("⚠" if ok > 0 else "❌")
                cells.append(f"{sym} {ok}/{n} ({pct}%)")
        summary.add_row(f"S{sid}: {scenario['name'][:25]}", *cells)

    console.print(summary)


def _print_rich(
    all_results: list[AgentScenarioResult],
    agents: list[str],
    repeat: int,
) -> None:
    console = Console()
    grouped: dict[int, dict[str, AgentScenarioResult]] = {}
    for r in all_results:
        grouped.setdefault(r.scenario_id, {})[r.agent] = r

    for sid, by_agent in grouped.items():
        _render_scenario_table(console, sid, by_agent, agents)

    _render_overall_summary(console, grouped, agents, repeat)


def _print_plain(
    all_results: list[AgentScenarioResult],
    agents: list[str],
) -> None:
    grouped: dict[int, dict[str, AgentScenarioResult]] = {}
    for r in all_results:
        grouped.setdefault(r.scenario_id, {})[r.agent] = r

    for sid, by_agent in grouped.items():
        scenario = SCENARIOS[sid]
        print(f"\n=== S{sid}: {scenario['name']} ===")
        for a in agents:
            if a not in by_agent:
                continue
            r = by_agent[a]
            ok, n = r.pass_rate(scenario)
            print(f"  [{a.upper()}] {ok}/{n} pass")
            print(f"    list_suggested: {r._rate('called_list_suggested')}")
            print(f"    inject_block:   {r._rate('called_inject')}")
            print(f"    submit:         {r._rate('called_submit')}")
            print(f"    blocks sample:  {r.sample_blocks()}")
            print(f"    avg duration:   {r.avg_duration()}")
            if r.errors():
                print(f"    errors: {r.errors()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Suppress telemetry for all benchmark runs — prevents eval UUIDs from polluting
    # PostHog cohorts. Inherited by all subprocess-spawned CLIs and MCP servers.
    os.environ["TURNZERO_TELEMETRY"] = "0"

    parser = argparse.ArgumentParser(
        description="TurnZero agentic benchmark — tests real AI CLIs against live library"
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=["claude", "gemini"],
        choices=["claude", "gemini", "codex"],
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        type=int,
        default=list(SCENARIOS.keys()),
        choices=list(SCENARIOS.keys()),
        metavar="N",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="Run each scenario N times and report pass rates",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (text or machine-readable json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.output_format == "text":
        print("TurnZero Agentic Benchmark")
        print(f"  Agents:    {args.agents}")
        print(f"  Scenarios: {args.scenarios}")
        print(f"  Repeat:    {args.repeat}×")
        print(f"  Data dir:  {TURNZERO_DATA_DIR}")
        print()

    all_results: list[AgentScenarioResult] = []

    for sid in args.scenarios:
        if args.output_format == "text":
            print(f"[S{sid}] {SCENARIOS[sid]['name']}...", flush=True)
        results = run_scenario(
            sid,
            args.agents,
            repeat=args.repeat,
            verbose=args.verbose,
        )
        all_results.extend(results)

    if args.output_format == "text":
        print()

    _print_results(all_results, args.agents, args.repeat, args.output_format)


if __name__ == "__main__":
    main()
