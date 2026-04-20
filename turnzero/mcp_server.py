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

from turnzero.blocks import Block, load_all_blocks
from turnzero.config import enabled_sources
from turnzero.retrieval import load_index
from turnzero.retrieval import query as _query

mcp = FastMCP(
    "turnzero",
    instructions=(
        "TurnZero injects Expert Priors at the start of AI sessions to prevent mid-session corrections. "
        "Expert Priors exist for any domain — software, law, medicine, finance, design, writing, and more. "
        "Call list_suggested_blocks at the start of every session with the user's opening prompt. "
        "Use inject_block to retrieve the formatted text for each relevant prior. "
        "During the session: if the user corrects you on any domain-specific fact, API, rule, or pattern, "
        "call submit_candidate with auto_approve=True — add it to the library immediately. "
        "Also call submit_candidate with auto_approve=True if the user explicitly says "
        "'remember this', 'save this', or 'note this for next time'. "
        "You are the best extractor — you already know which turns were corrections. "
        "Always use auto_approve=True for live sessions. "
        "The review queue (auto_approve=False) is only for offline harvest runs. "
        "Call get_stats when the user asks about TurnZero usage, stats, or how many priors have been injected."
    ),
)


# ---------------------------------------------------------------------------
# Path helpers (same as CLI — respects TURNZERO_DATA_DIR env var)
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    if env := os.environ.get("TURNZERO_DATA_DIR"):
        return Path(env)
    user_dir = Path.home() / ".turnzero"
    if user_dir.exists():
        return user_dir
    return Path("data")


def _blocks_dir() -> Path:
    return _data_dir() / "blocks"


def _index_path() -> Path:
    return _data_dir() / "index.jsonl"


def _active_sources() -> list[str]:
    return enabled_sources(_data_dir())


def _load_active_blocks() -> dict[str, Block]:
    return load_all_blocks(_blocks_dir(), sources=_active_sources())


# ---------------------------------------------------------------------------
# Pure tool logic (importable for testing without a live server)
# ---------------------------------------------------------------------------

def _list_suggested_blocks(
    prompt: str,
    top_k: int = 3,
    threshold: float = 0.75,
    context_weight: int = 4000,
    strict_intent: bool = True,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return ranked block suggestions for prompt as serialisable dicts."""
    sources = _active_sources()
    blocks = load_all_blocks(_blocks_dir(), sources=sources)
    index = load_index(_index_path(), sources=sources)
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
        return _list_suggested_blocks(prompt, project_root=Path.cwd())
    except RuntimeError as e:
        return [{
            "error": "no_embedding_backend",
            "message": str(e),
            "action": (
                "TurnZero needs an embedding backend to work. Choose one:\n\n"
                "  Option 1 — ollama (local, no internet after setup):\n"
                "    ollama serve && ollama pull nomic-embed-text\n\n"
                "  Option 2 — sentence-transformers (local, no server):\n"
                "    pip install 'turnzero[local]'\n\n"
                "  Option 3 — OpenAI API (cloud):\n"
                "    export OPENAI_API_KEY=sk-...\n\n"
                "Then restart your AI session."
            ),
        }]


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
    return _get_block(block_id)


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
    return _inject_block(block_id)


@mcp.tool()
def get_stats() -> dict:
    """Return TurnZero usage and library statistics.

    Call this when the user asks how TurnZero is doing, how many priors have
    been injected, or what domains are covered.

    Returns:
        Dict with sessions, priors injected, estimated turns saved, top domains,
        top blocks, library size, stale block count, and candidates pending review.
    """
    import json
    import time
    from collections import Counter
    from turnzero.blocks import load_all_blocks

    data_dir = _data_dir()
    log_path = data_dir / "hook_log.jsonl"
    entries: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    now = time.time()
    week_ago = now - 7 * 86400

    sessions_total = len(entries)
    sessions_week = sum(1 for e in entries if e.get("ts", 0) >= week_ago)
    priors_total = sum(len(e.get("blocks", [])) for e in entries)
    priors_week = sum(len(e.get("blocks", [])) for e in entries if e.get("ts", 0) >= week_ago)

    block_counts: Counter = Counter()
    domain_counts: Counter = Counter()
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

    return {
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
    }


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
    from turnzero.blocks import load_all_blocks

    today = __import__("datetime").date.today().isoformat()
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
    }

    if auto_approve:
        dest_dir = _blocks_dir() / "local" / domain
        dest_dir.mkdir(parents=True, exist_ok=True)
        block_path = dest_dir / f"{block_id}.yaml"
        with open(block_path, "w", encoding="utf-8") as f:
            _yaml.dump(block, f, allow_unicode=True, sort_keys=False)
        # Rebuild index
        from turnzero.index import build as build_index
        build_index(_blocks_dir(), _index_path())
        return (
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
        return (
            f"✓ Candidate '{block_id}' queued for review. "
            f"Run `turnzero review` to approve it into the library."
            + (f" Reason: {reason}" if reason else "")
        )


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
    from pathlib import Path

    # Ensure the conversations directory exists
    conv_dir = _data_dir() / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    # Write the transcript with a timestamp
    timestamp = int(time.time())
    file_path = conv_dir / f"{session_name}-{timestamp}.md"
    file_path.write_text(transcript, encoding="utf-8")

    return f"✓ Conversation logged to {file_path.name}. The Auto-Learn daemon will process it shortly."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
