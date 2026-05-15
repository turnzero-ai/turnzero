"""Stats service — usage logging and library statistics."""

from __future__ import annotations

import contextlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from turnzero.config import get_data_dir
from turnzero.types import INJECTION_TOOLS, StatsData, Tier


def log_injection(
    block_ids: list[str],
    domains: list[str],
    prompt_words: int,
    session_id: str | None = None,
    tokens_injected: int = 0,
) -> None:
    """Append a session entry to hook_log.jsonl so compute() reflects MCP injections."""
    entry = json.dumps(
        {
            "ts": time.time(),
            "blocks": block_ids,
            "domains": domains,
            "prompt_words": prompt_words,
            "source": "mcp",
            "session_id": session_id,
            "tokens_injected": tokens_injected,
        }
    )
    log_path = get_data_dir() / "hook_log.jsonl"
    try:
        get_data_dir().mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def log_tool_call(
    tool: str,
    input_obj: Any,
    output_obj: Any,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append one entry to tool_call_log.jsonl.

    Token counts are estimated from JSON-serialised size (chars / 4) — accurate
    enough for trend monitoring without adding a tokenizer dependency.
    """
    try:
        tokens_in = len(json.dumps(input_obj)) // 4
        tokens_out = len(json.dumps(output_obj)) // 4
        entry = json.dumps(
            {
                "ts": time.time(),
                "tool": tool,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                **(meta or {}),
            }
        )
        log_path = get_data_dir() / "tool_call_log.jsonl"
        get_data_dir().mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


# Use the canonical set from types — single source of truth
_INJECTION_TOOLS = INJECTION_TOOLS


def _aggregate_tool_tokens(
    entries: list[dict[str, Any]], week_ago: float
) -> dict[str, Any]:
    by_tool: Counter[str] = Counter()
    tokens_in_total = tokens_out_total = tokens_in_week = tokens_out_week = 0
    submit_tokens_total = injection_overhead_total = injection_overhead_week = 0
    for e in entries:
        tool = e.get("tool", "unknown")
        by_tool[tool] += 1
        tin, tout = e.get("tokens_in", 0), e.get("tokens_out", 0)
        tokens_in_total += tin
        tokens_out_total += tout
        is_recent = e.get("ts", 0) >= week_ago
        if is_recent:
            tokens_in_week += tin
            tokens_out_week += tout
        if tool == "submit_candidate":
            submit_tokens_total += tin + tout
        if tool in _INJECTION_TOOLS:
            injection_overhead_total += tin + tout
            if is_recent:
                injection_overhead_week += tin + tout
    return {
        "by_tool": by_tool,
        "tokens_in_total": tokens_in_total,
        "tokens_out_total": tokens_out_total,
        "tokens_in_week": tokens_in_week,
        "tokens_out_week": tokens_out_week,
        "submit_tokens_total": submit_tokens_total,
        "injection_overhead_total": injection_overhead_total,
        "injection_overhead_week": injection_overhead_week,
    }


def compute_display_data(data_dir: Path) -> dict[str, Any]:  # noqa: PLR0912, PLR0915
    """Aggregate all stats for CLI display. Headless — no rendering or side effects."""
    import datetime
    from collections import Counter as _Counter

    from turnzero.types import INJECTION_TOOLS as _INJECTION_TOOLS

    log_path = data_dir / "hook_log.jsonl"
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))

    import time as _time

    now = _time.time()
    week_ago = now - 7 * 86400

    sessions_total = len(entries)
    sessions_week = sum(1 for e in entries if e.get("ts", 0) >= week_ago)
    priors_total = sum(len(e.get("blocks", [])) for e in entries)
    priors_week = sum(
        len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago
    )
    tokens_injected_total = sum(e.get("tokens_injected", 0) for e in entries)
    tokens_injected_week = sum(
        e.get("tokens_injected", 0) for e in entries if e.get("ts", 0) >= week_ago
    )

    tool_log_path = data_dir / "tool_call_log.jsonl"
    tool_entries: list[dict[str, Any]] = []
    if tool_log_path.exists():
        for line in tool_log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                tool_entries.append(json.loads(line))

    overhead_total = sum(
        e.get("tokens_in", 0) + e.get("tokens_out", 0)
        for e in tool_entries
        if e.get("tool") in _INJECTION_TOOLS
    )
    overhead_week = sum(
        e.get("tokens_in", 0) + e.get("tokens_out", 0)
        for e in tool_entries
        if e.get("tool") in _INJECTION_TOOLS and e.get("ts", 0) >= week_ago
    )
    corrections_total = sum(
        1
        for e in tool_entries
        if e.get("tool") == "submit_candidate"
        and not e.get("meta", {}).get("auto_approve", True)
    )
    corrections_week = sum(
        1
        for e in tool_entries
        if e.get("tool") == "submit_candidate"
        and not e.get("meta", {}).get("auto_approve", True)
        and e.get("ts", 0) >= week_ago
    )

    domain_counts: _Counter[str] = _Counter()
    for e in entries:
        for d in e.get("domains", []):
            domain_counts[d] += 1

    top_domains = [d for d, _ in domain_counts.most_common(5)]

    from turnzero.analytics import TOKENS_PER_TURN, TURNS_SAVED_PER_INJECTION

    est_turns = round(priors_total * TURNS_SAVED_PER_INJECTION)
    est_tokens = priors_total * TURNS_SAVED_PER_INJECTION * TOKENS_PER_TURN

    from turnzero.repositories.block_repo import load_all_blocks

    try:
        from turnzero.config import get_blocks_dir

        blocks = load_all_blocks(get_blocks_dir())
    except FileNotFoundError:
        blocks = {}

    stale_count = sum(1 for b in blocks.values() if b.is_stale())
    personal_blocks = [b for b in blocks.values() if b.tier == Tier.PERSONAL]
    personal_count = len(personal_blocks)

    personal_weeks: int | None = None
    if personal_blocks:
        with contextlib.suppress(ValueError):
            earliest = min(b.last_verified for b in personal_blocks)
            delta = datetime.date.today() - datetime.date.fromisoformat(earliest)
            personal_weeks = max(1, delta.days // 7)

    index_count: int | None = None
    with contextlib.suppress(FileNotFoundError):
        from turnzero.config import get_index_path
        from turnzero.repositories.index_repo import load_index

        index_count = len(load_index(get_index_path()))

    return {
        "sessions_total": sessions_total,
        "sessions_week": sessions_week,
        "priors_total": priors_total,
        "priors_week": priors_week,
        "tokens_injected_total": tokens_injected_total,
        "tokens_injected_week": tokens_injected_week,
        "overhead_total": overhead_total,
        "overhead_week": overhead_week,
        "corrections_total": corrections_total,
        "corrections_week": corrections_week,
        "top_domains": top_domains,
        "est_turns": est_turns,
        "est_tokens": est_tokens,
        "blocks_total": len(blocks),
        "personal_count": personal_count,
        "personal_weeks": personal_weeks,
        "stale_count": stale_count,
        "index_count": index_count,
        "data_dir": data_dir,
    }


def compute() -> StatsData:
    """Return TurnZero usage and library statistics."""
    from turnzero.services.retrieval_svc import _load_active_blocks

    data_dir = get_data_dir()
    log_path = data_dir / "hook_log.jsonl"
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))

    now = time.time()
    week_ago = now - 7 * 86400

    sessions_total = len(entries)
    sessions_week = sum(1 for e in entries if e.get("ts", 0) >= week_ago)
    priors_total = sum(len(e.get("blocks", [])) for e in entries)
    priors_week = sum(
        len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago
    )

    block_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for e in entries:
        for slug in e.get("blocks", []):
            block_counts[slug] += 1
        for d in e.get("domains", []):
            domain_counts[d] += 1

    tokens_injected_total = sum(e.get("tokens_injected", 0) for e in entries)
    tokens_injected_week = sum(
        e.get("tokens_injected", 0) for e in entries if e.get("ts", 0) >= week_ago
    )

    from turnzero.analytics import TOKENS_PER_TURN, TURNS_SAVED_PER_INJECTION

    est_turns = round(priors_total * TURNS_SAVED_PER_INJECTION)
    est_tokens = round(priors_total * TURNS_SAVED_PER_INJECTION * TOKENS_PER_TURN)

    try:
        blocks = _load_active_blocks()
    except FileNotFoundError:
        blocks = {}

    stale_count = sum(1 for b in blocks.values() if b.is_stale())
    personal_count = sum(1 for b in blocks.values() if b.tier == Tier.PERSONAL)
    candidates_dir = data_dir / "candidates"
    candidates = list(candidates_dir.glob("*.yaml")) if candidates_dir.exists() else []

    tool_log_path = data_dir / "tool_call_log.jsonl"
    tool_entries: list[dict[str, Any]] = []
    if tool_log_path.exists():
        for line in tool_log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                tool_entries.append(json.loads(line))

    tool_calls_total = len(tool_entries)
    tool_calls_week = sum(1 for e in tool_entries if e.get("ts", 0) >= week_ago)
    tool_stats = _aggregate_tool_tokens(tool_entries, week_ago)

    return {
        "sessions": {"total": sessions_total, "this_week": sessions_week},
        "priors_injected": {"total": priors_total, "this_week": priors_week},
        "context_tokens_injected": {
            "total": tokens_injected_total,
            "this_week": tokens_injected_week,
            "note": "estimated from context_weight (word_count x 4), not a real tokenizer",
        },
        "injection_overhead": {
            "total": tool_stats["injection_overhead_total"],
            "this_week": tool_stats["injection_overhead_week"],
            "note": "MCP call tokens for list_suggested_blocks + inject_block (len(json) // 4)",
        },
        "estimated_turns_saved": est_turns,
        "estimated_tokens_saved": est_tokens,
        "top_domains": [d for d, _ in domain_counts.most_common(5)],
        "top_blocks": [
            {"block_id": slug, "count": count}
            for slug, count in block_counts.most_common(3)
        ],
        "library": {
            "total_blocks": len(blocks),
            "personal_blocks": personal_count,
            "expert_blocks": len(blocks) - personal_count,
            "stale_blocks": stale_count,
            "candidates_pending_review": len(candidates),
        },
        "tool_calls": {
            "total": tool_calls_total,
            "this_week": tool_calls_week,
            "by_tool": dict(tool_stats["by_tool"].most_common()),
        },
        "token_cost": {
            "total_in": tool_stats["tokens_in_total"],
            "total_out": tool_stats["tokens_out_total"],
            "total": tool_stats["tokens_in_total"] + tool_stats["tokens_out_total"],
            "this_week": tool_stats["tokens_in_week"] + tool_stats["tokens_out_week"],
            "submit_candidate_total": tool_stats["submit_tokens_total"],
        },
    }
