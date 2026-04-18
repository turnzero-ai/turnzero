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
from turnzero.retrieval import load_index
from turnzero.retrieval import query as _query

mcp = FastMCP(
    "turnzero",
    instructions=(
        "TurnZero suggests and injects curated Expert Priors for developer AI sessions. "
        "Call list_suggested_blocks at the start of a session to get relevant constraints, "
        "anti-patterns, and doc anchors for the user's opening prompt. "
        "Use inject_block to retrieve the formatted text ready to prepend to your context. "
        "Call learn_from_session if the user provides a correction or if a new expert pattern is identified."
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
    blocks = load_all_blocks(_blocks_dir())
    index = load_index(_index_path())
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
    blocks = load_all_blocks(_blocks_dir())
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
    blocks = load_all_blocks(_blocks_dir())
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
    """
    return _list_suggested_blocks(prompt, project_root=Path.cwd())


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
