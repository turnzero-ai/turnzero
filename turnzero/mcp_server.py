"""TurnZero MCP server — three tools for AI session context injection.

Install:  pip install turnzero
Run:      turnzero-mcp
Add to Claude Code .claude/settings.json:
  {
    "mcpServers": {
      "turnzero": {
        "command": "/path/to/.venv/bin/turnzero-mcp"
      }
    }
  }
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from turnzero.blocks import Block, compute_confidence, load_all_blocks
from turnzero.config import enabled_sources
from turnzero.retrieval import IndexEntry, load_index
from turnzero.retrieval import query as _query

# ---------------------------------------------------------------------------
# Per-source index cache: path → (mtime, entries)
# Avoids re-reading disk on every Turn 0 — reloads only when file changes.
# ---------------------------------------------------------------------------
_INDEX_CACHE: dict[Path, tuple[float, list[IndexEntry]]] = {}

mcp = FastMCP(
    "turnzero",
    instructions=(
        "TurnZero injects Expert Priors to prevent mid-session corrections. "
        "Expert Priors exist for any domain — software, law, medicine, finance, security, writing, and more. "
        "\n\n"
        "RULE 1 — ALWAYS call list_suggested_blocks before responding to ANY non-trivial user message. "
        "Do not wait — call it in parallel with preparing your response. "
        "This applies to every message, not just the first one in a session. "
        "Skip only for pure chitchat (greetings, thanks, one-word replies). "
        "Use inject_block to retrieve the full text of each relevant prior before answering. "
        "\n\n"
        "RULE 2 — ALWAYS call submit_candidate with auto_approve=True when: "
        "(a) the user corrects you on any domain-specific fact, API, rule, pattern, or threshold; "
        "(b) the user says 'remember this', 'save this', or 'note this for next time'. "
        "Do this immediately — do not wait until the end of the session. "
        "You are the best extractor: you already know which turns were corrections. "
        "\n\n"
        "Always use auto_approve=True for live sessions. "
        "The review queue (auto_approve=False) is only for offline harvest runs. "
        "Call get_stats when the user asks about TurnZero usage or how many priors have been injected."
    ),
)


from turnzero.config import (
    _blocks_dir,
    _bundled_blocks_dir,
    _bundled_index_path,
    _data_dir,
    _index_path,
    enabled_sources,
)

# ---------------------------------------------------------------------------
# Path helpers (centralized in config.py)
# ---------------------------------------------------------------------------

def _active_sources() -> list[str]:
    return enabled_sources(_data_dir())


def _load_active_blocks() -> dict[str, Block]:
    blocks_dir = _blocks_dir()
    if not blocks_dir.exists():
        # Fallback to bundled blocks
        blocks_dir = _bundled_blocks_dir()
    return load_all_blocks(blocks_dir, sources=_active_sources())


def _load_source_index(source: str) -> list[IndexEntry]:
    """Load index for one source tier, using mtime-based cache."""
    data_dir = _data_dir()
    per_source_path = data_dir / f"index_{source}.jsonl"
    
    path = per_source_path if per_source_path.exists() else _index_path()
    
    if not path.exists():
        # Fallback to bundled index
        path = _bundled_index_path()

    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return []

    cached = _INDEX_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    entries = load_index(path, sources=[source] if path == _index_path() else None)
    _INDEX_CACHE[path] = (mtime, entries)
    return entries


def _load_active_index() -> list[IndexEntry]:
    """Load and merge index entries for all enabled sources, with caching."""
    result: list[IndexEntry] = []
    for source in _active_sources():
        result.extend(_load_source_index(source))
    return result


# ---------------------------------------------------------------------------
# Pure tool logic (importable for testing without a live server)
# ---------------------------------------------------------------------------

def _list_suggested_blocks(
    prompt: str,
    top_k: int = 3,
    threshold: float = 0.70,
    context_weight: int = 4000,
    strict_intent: bool = True,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return ranked block suggestions for prompt as serialisable dicts."""
    blocks = _load_active_blocks()
    index = _load_active_index()
    results = _query(
        prompt, index, blocks,
        top_k=top_k, threshold=threshold, context_weight=context_weight,
        strict_intent=strict_intent,
        project_root=project_root,
    )
    return [
        {
            "block_id": block.slug,
            "score": round(score, 3),
            "domain": block.domain,
            "intent": block.intent,
            "tags": block.tags,
            "context_weight": block.context_weight,
            "stale": block.is_stale(),
            "preview": block.constraints[0][:120] if block.constraints else "",
        }
        for block, score in results
    ]


def _get_block(block_id: str) -> dict[str, Any]:
    """Return full block data as a serialisable dict."""
    blocks = _load_active_blocks()
    if block_id not in blocks:
        available = sorted(blocks.keys())
        raise ValueError(
            f"Block '{block_id}' not found. "
            f"Available blocks: {', '.join(available)}"
        )
    block: Block = blocks[block_id]
    return {
        "id": block.slug,
        "slug": block.slug,
        "hash": block.hash,
        "version": block.version,
        "domain": block.domain,
        "intent": block.intent,
        "last_verified": block.last_verified,
        "stale": block.is_stale(),
        "tags": block.tags,
        "context_weight": block.context_weight,
        "provides": block.provides,
        "conflicts_with_tags": block.conflicts_with_tags,
        "constraints": block.constraints,
        "anti_patterns": block.anti_patterns,
        "doc_anchors": [
            {"url": a.url, "verified": a.verified}
            for a in block.doc_anchors
        ],
        "conflicts_with": block.conflicts_with,
        "requires": block.requires,
    }


def _inject_block(block_id: str) -> str:
    """Return formatted injection text for a block."""
    blocks = _load_active_blocks()
    if block_id not in blocks:
        available = sorted(blocks.keys())
        raise ValueError(
            f"Block '{block_id}' not found. "
            f"Available blocks: {', '.join(available)}"
        )
    return blocks[block_id].to_injection_text()


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------

def _log_mcp_injection(block_ids: list[str], domains: list[str], prompt_words: int) -> None:
    """Append a session entry to hook_log.jsonl so get_stats reflects MCP injections."""
    import json
    import time

    entry = json.dumps({
        "ts": time.time(),
        "blocks": block_ids,
        "domains": domains,
        "prompt_words": prompt_words,
        "source": "mcp",
    })
    log_path = _data_dir() / "hook_log.jsonl"
    try:
        _data_dir().mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def _log_tool_call(
    tool: str,
    input_obj: Any,
    output_obj: Any,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append one entry to tool_call_log.jsonl tracking per-tool call counts and token cost.

    Token counts are estimated from JSON-serialised size (chars / 4) — accurate enough
    for trend monitoring without adding a tokenizer dependency.
    """
    import json
    import time

    try:
        tokens_in = len(json.dumps(input_obj)) // 4
        tokens_out = len(json.dumps(output_obj)) // 4
        entry = json.dumps({
            "ts": time.time(),
            "tool": tool,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            **(meta or {}),
        })
        log_path = _data_dir() / "tool_call_log.jsonl"
        _data_dir().mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


@mcp.tool()
def list_suggested_blocks(prompt: str) -> list[dict[str, Any]]:
    """Suggest Expert Priors relevant to an opening developer prompt.

    Returns up to 3 ranked Expert Priors with scores, tags, context weights,
    and a preview of the first constraint. Call this at the start of
    a session before the user's first question.

    Args:
        prompt: The user's opening prompt or session description.

    Returns:
        List of Expert Prior suggestions, ranked by relevance score.
        Each item has: block_id, score, domain, intent, tags,
        context_weight, stale, preview.
        Returns a single error entry if no embedding backend is configured.
    """
    try:
        suggestions = _list_suggested_blocks(prompt, project_root=Path.cwd())
        if suggestions:
            _log_mcp_injection(
                block_ids=[s["block_id"] for s in suggestions],
                domains=list({s["domain"] for s in suggestions}),
                prompt_words=len(prompt.split()),
            )
        _log_tool_call("list_suggested_blocks", {"prompt": prompt}, suggestions)
        return suggestions
    except RuntimeError as e:
        result = [{
            "error": "no_embedding_backend",
            "message": str(e),
            "action": (
                "TurnZero needs an embedding backend to work. Choose one:\n\n"
                "  Option 1 — ollama (local, no internet after setup):\n"
                "    ollama serve && ollama pull nomic-embed-text\n\n"
                "  Option 2 — OpenAI API (cloud):\n"
                "    export OPENAI_API_KEY=sk-...\n\n"
                "Then restart your AI session."
            ),
        }]
        _log_tool_call("list_suggested_blocks", {"prompt": prompt}, result)
        return result


@mcp.tool()
def get_block(block_id: str) -> dict[str, Any]:
    """Return the full content of an Expert Prior by ID.

    Use this after list_suggested_blocks to inspect a specific Expert Prior
    before deciding whether to inject it.

    Args:
        block_id: The block identifier (e.g. 'nextjs15-approuter-build').

    Returns:
        Full Expert Prior data including all constraints, anti-patterns,
        doc anchors, version, staleness status, and context weight.
    """
    result = _get_block(block_id)
    _log_tool_call("get_block", {"block_id": block_id}, result)
    return result


@mcp.tool()
def inject_block(block_id: str) -> str:
    """Return a formatted Expert Prior ready for injection into an AI session.

    The returned markdown string contains constraints, anti-patterns, and
    doc anchors formatted for direct prepending to your system context.
    Injection is always client-side — this tool never contacts the AI provider.

    Args:
        block_id: The block identifier (e.g. 'nextjs15-approuter-build').

    Returns:
        Formatted markdown Expert Prior, ready to inject before the
        first AI response.
    """
    result = _inject_block(block_id)
    _log_tool_call("inject_block", {"block_id": block_id}, result)
    return result


@mcp.tool()
def get_stats() -> dict[str, Any]:
    """Return TurnZero usage and library statistics.

    Call this when the user asks how TurnZero is doing, how many priors have
    been injected, or what domains are covered.

    Returns:
        Dict with sessions, priors injected, estimated turns saved, top domains,
        top blocks, library size, stale block count, and candidates pending review.
    """
    import contextlib
    import json
    import time
    from collections import Counter

    data_dir = _data_dir()
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
    priors_week = sum(len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago)

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
    candidates = list((_data_dir() / "candidates").glob("*.yaml")) if (_data_dir() / "candidates").exists() else []

    # ── Tool call log ──────────────────────────────────────────────────────
    tool_log_path = data_dir / "tool_call_log.jsonl"
    tool_entries: list[dict[str, Any]] = []
    if tool_log_path.exists():
        for line in tool_log_path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                tool_entries.append(json.loads(line))

    tool_calls_total = len(tool_entries)
    tool_calls_week = sum(1 for e in tool_entries if e.get("ts", 0) >= week_ago)

    by_tool: Counter[str] = Counter()
    tokens_in_total = 0
    tokens_out_total = 0
    tokens_in_week = 0
    tokens_out_week = 0
    submit_tokens_total = 0
    for e in tool_entries:
        by_tool[e.get("tool", "unknown")] += 1
        tin = e.get("tokens_in", 0)
        tout = e.get("tokens_out", 0)
        tokens_in_total += tin
        tokens_out_total += tout
        if e.get("ts", 0) >= week_ago:
            tokens_in_week += tin
            tokens_out_week += tout
        if e.get("tool") == "submit_candidate":
            submit_tokens_total += tin + tout

    result: dict[str, Any] = {
        "sessions": {"total": sessions_total, "this_week": sessions_week},
        "priors_injected": {"total": priors_total, "this_week": priors_week},
        "estimated_turns_saved": est_turns,
        "estimated_tokens_saved": est_tokens,
        "top_domains": [d for d, _ in domain_counts.most_common(5)],
        "top_blocks": [{"block_id": slug, "count": count} for slug, count in block_counts.most_common(3)],
        "library": {
            "total_blocks": len(blocks),
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
    _log_tool_call("get_stats", {}, result)
    return result


@mcp.tool()
def submit_candidate(
    block_id: str,
    domain: str,
    intent: str,
    constraints: list[str],
    anti_patterns: list[str],
    tags: list[str] | None = None,
    doc_anchors: list[str] | None = None,
    reason: str = "",
    auto_approve: bool = False,
) -> str:
    """Submit an Expert Prior candidate identified during this session.

    Call this when the user corrects you mid-session on any domain: wrong library,
    wrong legal rule, wrong medical threshold, wrong financial formula, deprecated API,
    or any domain-specific truth you got wrong. Works for software, law, medicine,
    finance, design, writing — any field. You are the extractor — write the prior
    directly rather than waiting for a harvest pass.

    Always set auto_approve=True for corrections detected during a live session —
    the block is added to the library immediately and the index is rebuilt.

    Set auto_approve=False only when submitting from an offline harvest run
    where human review is desired before the block goes live.

    Args:
        block_id: Descriptive slug, e.g. 'nextjs15-approuter-debug'.
        domain: Primary technology, lowercase single word, e.g. 'nextjs', 'fastapi'.
        intent: One of: build, debug, migrate, review.
        constraints: Rules the AI should follow. Each must be specific and version-anchored.
        anti_patterns: Things the AI should NOT do. Each must start with 'Do not'.
        tags: Optional list of relevant tags.
        doc_anchors: Optional list of official documentation URLs.
        reason: Why this prior is worth adding — what went wrong this session.
        auto_approve: If True, add directly to the block library and rebuild the index.
                      Use when the user explicitly requested this to be remembered.

    Returns:
        Confirmation that the candidate was saved or approved into the library.
    """
    import yaml as _yaml

    today = __import__("datetime").date.today().isoformat()
    confidence = compute_confidence(block_id, constraints, anti_patterns or [], tags or [], reason)
    block = {
        "id": block_id,
        "slug": block_id,
        "version": "1.0.0",
        "domain": domain,
        "intent": intent,
        "last_verified": today,
        "tags": tags or [],
        "context_weight": sum(len(c.split()) * 4 for c in constraints + (anti_patterns or [])),
        "conflicts_with": [],
        "requires": [],
        "constraints": constraints,
        "anti_patterns": anti_patterns or [],
        "doc_anchors": [{"url": u, "verified": today} for u in (doc_anchors or [])],
        "confidence": confidence,
        "archived": False,
    }

    input_snapshot = {
        "block_id": block_id, "domain": domain, "intent": intent,
        "constraints": constraints, "anti_patterns": anti_patterns or [],
        "tags": tags or [], "doc_anchors": doc_anchors or [],
        "reason": reason, "auto_approve": auto_approve,
    }
    if auto_approve:
        dest_dir = _blocks_dir() / "local" / domain
        dest_dir.mkdir(parents=True, exist_ok=True)
        block_path = dest_dir / f"{block_id}.yaml"
        with open(block_path, "w", encoding="utf-8") as f:
            _yaml.dump(block, f, allow_unicode=True, sort_keys=False)
        # Rebuild index
        from turnzero.index import build as build_index
        build_index(_blocks_dir(), _index_path(), data_dir=_data_dir())
        result = (
            f"✓ Expert Prior '{block_id}' added to library and index rebuilt. "
            f"It will be injected in future sessions matching this domain."
            + (f" Reason: {reason}" if reason else "")
        )
    else:
        candidates_dir = _data_dir() / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidates_dir / f"{block_id}.yaml"
        with open(candidate_path, "w", encoding="utf-8") as f:
            _yaml.dump(block, f, allow_unicode=True, sort_keys=False)
        result = (
            f"✓ Candidate '{block_id}' queued for review. "
            f"Run `turnzero review` to approve it into the library."
            + (f" Reason: {reason}" if reason else "")
        )
    _log_tool_call(
        "submit_candidate", input_snapshot, result,
        meta={"auto_approve": auto_approve, "block_id": block_id},
    )
    return result


@mcp.tool()
def learn_from_session(transcript: str, session_name: str = "mcp-session") -> str:
    """Save a conversation transcript for automatic Expert Prior extraction.

    Call this tool when a user provides a correction, clarifies a version
    requirement, or when an expert pattern is identified that should be
    remembered for future sessions.

    Args:
        transcript: The full text of the conversation or the relevant turns.
        session_name: A descriptive name for the session (optional).

    Returns:
        A success message indicating the log has been queued for auto-learning.
    """
    import time

    # Ensure the conversations directory exists
    conv_dir = _data_dir() / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    # Write the transcript with a timestamp
    timestamp = int(time.time())
    file_path = conv_dir / f"{session_name}-{timestamp}.md"
    file_path.write_text(transcript, encoding="utf-8")

    return (
        f"✓ Conversation logged to {file_path.name}. "
        "Run `turnzero harvest` to extract Expert Priors from this transcript."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
