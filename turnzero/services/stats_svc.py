"""Stats service — usage logging and library statistics."""

from __future__ import annotations

import contextlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from turnzero.config import get_data_dir


def log_injection(
    block_ids: list[str],
    domains: list[str],
    prompt_words: int,
    session_id: str | None = None,
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


def compute() -> dict[str, Any]:
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

    est_turns = round(priors_total * 0.5)
    est_tokens = round(priors_total * 0.5 * 1500)

    try:
        blocks = _load_active_blocks()
    except FileNotFoundError:
        blocks = {}

    stale_count = sum(1 for b in blocks.values() if b.is_stale())
    personal_count = sum(1 for b in blocks.values() if b.tier == "personal")
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

    by_tool: Counter[str] = Counter()
    tokens_in_total = tokens_out_total = tokens_in_week = tokens_out_week = 0
    submit_tokens_total = 0
    for e in tool_entries:
        by_tool[e.get("tool", "unknown")] += 1
        tin, tout = e.get("tokens_in", 0), e.get("tokens_out", 0)
        tokens_in_total += tin
        tokens_out_total += tout
        if e.get("ts", 0) >= week_ago:
            tokens_in_week += tin
            tokens_out_week += tout
        if e.get("tool") == "submit_candidate":
            submit_tokens_total += tin + tout

    return {
        "sessions": {"total": sessions_total, "this_week": sessions_week},
        "priors_injected": {"total": priors_total, "this_week": priors_week},
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
            "by_tool": dict(by_tool.most_common()),
        },
        "token_cost": {
            "total_in": tokens_in_total,
            "total_out": tokens_out_total,
            "total": tokens_in_total + tokens_out_total,
            "this_week": tokens_in_week + tokens_out_week,
            "submit_candidate_total": submit_tokens_total,
        },
    }
