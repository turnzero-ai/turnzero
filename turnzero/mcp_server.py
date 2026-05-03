"""TurnZero MCP server — thin adapter over service layer.

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

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from turnzero.services import candidate_svc, retrieval_svc, stats_svc
from turnzero.validators import validate_session_name, safe_path
from turnzero.config import get_data_dir

# ---------------------------------------------------------------------------
# Re-exports for test compat (tests import these names from mcp_server)
# ---------------------------------------------------------------------------
_INDEX_CACHE = retrieval_svc._INDEX_CACHE
_list_suggested_blocks = retrieval_svc.list_suggested_blocks
_get_block = retrieval_svc.get_block
_inject_block = retrieval_svc.inject_block
_log_mcp_injection = stats_svc.log_injection
_log_tool_call = stats_svc.log_tool_call

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "turnzero",
    instructions=(
        "TurnZero injects Expert Priors to prevent mid-session corrections. "
        "Expert Priors exist for any domain — software, law, medicine, finance, security, writing, and more. "
        "\n\n"
        "RULE 1 — ALWAYS call list_suggested_blocks before responding to ANY non-trivial user message. "
        "Do not wait — call it in parallel with preparing your response. "
        "This retrieves your Personal Priors (Identity) and relevant Expert Priors (Domain Knowledge). "
        "Use inject_block to retrieve the full text of each relevant prior before answering. "
        "\n\n"
        "RULE 2 — ALWAYS call submit_candidate when: "
        "(a) the user corrects you on any domain-specific fact, API, rule, pattern, or threshold; "
        "(b) the user says 'remember this', 'save this', or 'note this for next time'. "
        "Use is_personal=True for idiosyncratic user preferences and is_personal=False for general technical truths. "
        "Set auto_approve=True ONLY if the user explicitly asked you to remember/save the rule. "
        "Otherwise, set auto_approve=False so the user can review it later. "
        "Do this immediately — do not wait until the end of the session. "
        "\n\n"
        "RULE 3 — Call reset_session if the user requests a fresh start, clear history, or session reset. "
        "This ensures Personal Priors are re-suggested in the next turn."
    ),
)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


@mcp.tool()
def list_suggested_blocks(
    prompt: str, session_id: str | None = None
) -> list[dict[str, Any]]:
    """Suggest Expert Priors relevant to an opening developer prompt.

    Returns Personal Priors (always-on identity) and relevant Expert Priors.
    Call this at the start of a session before the user's first question.

    IMPORTANT: preview text is for relevance filtering ONLY — it is intentionally
    truncated and incomplete. You MUST call inject_block for every suggested block
    before using or applying any prior content. Never infer or apply constraints
    from a preview without calling inject_block first.

    Args:
        prompt: The user's opening prompt or session description.
        session_id: Optional session identifier for deduplication.

    Returns:
        List of Expert Prior suggestions, ranked by relevance score.
        Each item has: block_id, score, domain, intent, tags,
        context_weight, stale, preview.
        Returns a single error entry if no embedding backend is configured.
    """
    try:
        suggestions = retrieval_svc.list_suggested_blocks(
            prompt, project_root=Path.cwd(), session_id=session_id
        )
        stats_svc.log_tool_call(
            "list_suggested_blocks",
            {"prompt": prompt, "session_id": session_id},
            suggestions,
        )
        return suggestions
    except RuntimeError as e:
        result = [
            {
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
            }
        ]
        stats_svc.log_tool_call("list_suggested_blocks", {"prompt": prompt}, result)
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
    result = retrieval_svc.get_block(block_id)
    stats_svc.log_tool_call("get_block", {"block_id": block_id}, result)
    return result


@mcp.tool()
def inject_block(block_id: str, session_id: str | None = None) -> str:
    """Return a formatted Expert Prior ready for injection into an AI session.

    The returned markdown string contains constraints, anti-patterns, and
    doc anchors formatted for direct prepending to your system context.
    Injection is always client-side — this tool never contacts the AI provider.

    Args:
        block_id: The block identifier (e.g. 'nextjs15-approuter-build').
        session_id: Optional session identifier for deduplication.

    Returns:
        Formatted markdown Expert Prior, ready to inject before the
        first AI response.
    """
    result = retrieval_svc.inject_block(
        block_id, session_id=session_id, project_root=Path.cwd()
    )
    stats_svc.log_tool_call(
        "inject_block",
        {"block_id": block_id, "session_id": session_id},
        result,
        meta={"block_id": block_id},
    )
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
    result = stats_svc.compute()
    stats_svc.log_tool_call("get_stats", {}, result)
    return result


@mcp.tool()
def reset_session(session_id: str | None = None) -> str:
    """Clear TurnZero's injection memory for the current session.

    Call this tool when the user explicitly asks to 'reset', 'clear history',
    'start over', or 'forget context'. This ensures that the user's
    Portable Identity (Personal Priors) and relevant Expert Priors are
    re-suggested in the next turn.
    """
    return retrieval_svc.reset_session(session_id)



@mcp.tool()
def submit_candidate(
    block_id: str,
    domain: str,
    intent: str,
    constraints: list[str],
    anti_patterns: list[str],
    tags: list[str] | None = None,
    doc_anchors: list[str] | None = None,
    rationale: str | None = None,
    reason: str = "",
    auto_approve: bool = False,
    is_personal: bool = False,
    project_root: str | None = None,
) -> str:
    """Submit an Expert Prior candidate identified during this session.

    Call this when the user corrects you mid-session on any domain: wrong library,
    wrong legal rule, wrong medical threshold, wrong financial formula, deprecated API,
    or any domain-specific truth you got wrong. Works for software, law, medicine,
    finance, design, writing — any field. You are the extractor — write the prior
    directly rather than waiting for a harvest pass.

    PERSONAL PRIORS (is_personal=True):
    Set is_personal=True if the correction is about the user's idiosyncratic
    preferences, personal coding style, or project-specific workflow rules that
    should ALWAYS be remembered for this user/project, regardless of general
    technical truth. These are saved to a private local 'personal' tier.

    PROJECT PINNING:
    If is_personal=True and domain != 'global', the prior is automatically pinned
    to the current project if project_root is provided.

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
        rationale: Research-backed reason for the constraints and anti-patterns.
        reason: Why this prior is worth adding — what went wrong this session.
        auto_approve: If True, add directly to the library and rebuild the index.
        is_personal: If True, save to the private 'personal' tier instead of 'local'.
        project_root: Optional path to current project to pin personal priors.
    """
    result, input_snapshot = candidate_svc.submit(
        block_id=block_id,
        domain=domain,
        intent=intent,
        constraints=constraints,
        anti_patterns=anti_patterns,
        tags=tags,
        doc_anchors=doc_anchors,
        rationale=rationale,
        reason=reason,
        auto_approve=auto_approve,
        is_personal=is_personal,
        project_root=project_root,
    )
    stats_svc.log_tool_call(
        "submit_candidate",
        input_snapshot,
        result,
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

    validate_session_name(session_name)
    conv_dir = get_data_dir() / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    file_path = safe_path(conv_dir, f"{session_name}-{timestamp}.md")
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
