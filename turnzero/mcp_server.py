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

import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from turnzero.config import get_data_dir
from turnzero.services import candidate_svc, retrieval_svc, stats_svc
from turnzero.types import (
    BLOCK_ID_NO_MATCH_HINT,
    BLOCK_ID_PERSONAL_LIMIT_WARNING,
    BlockData,
    StatsData,
    SuggestionEntry,
)
from turnzero.validators import safe_path, validate_session_name

# ---------------------------------------------------------------------------
# WF-1: Process-scoped session identity
# ---------------------------------------------------------------------------
# Generated once at server startup; used when the agent passes no session_id.
# Rotated automatically after _SESSION_TTL to prevent cross-conversation bleed
# when the MCP process spans multiple user conversations.
# Explicitly rotated by reset_session() so agents that call it get a clean slate.

_SESSION_TTL: float = 4 * 3600.0  # 4 hours

# Mutable container avoids module-level reassignment (PLW0603).
_proc_session: dict[str, float | str] = {
    "id": str(uuid.uuid4()),
    "started": time.time(),
}


def _effective_session_id(caller_id: str | None) -> str:
    if caller_id:
        return caller_id
    if time.time() - float(_proc_session["started"]) > _SESSION_TTL:
        _proc_session["id"] = str(uuid.uuid4())
        _proc_session["started"] = time.time()
    return str(_proc_session["id"])


def _rotate_proc_session() -> None:
    _proc_session["id"] = str(uuid.uuid4())
    _proc_session["started"] = time.time()


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
        "SKIP list_suggested_blocks only for pure chitchat — greetings, social acknowledgments "
        "('thanks', 'looks good', 'got it'), or any message with no actionable content. "
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
    prompt: str,
    session_id: str | None = None,
    inject_all: bool = False,
) -> list[SuggestionEntry]:
    """Suggest Expert Priors relevant to an opening developer prompt.

    Returns Personal Priors (always-on identity) and relevant Expert Priors.
    Call this at the start of a session before the user's first question.

    Each result includes a "turn" field: "first" means Personal Priors are
    included (inject them now); "subsequent" means they were already injected
    this session and are omitted — only new Expert Priors are returned.

    Set inject_all=True to receive full block text inline ("full_text" field)
    and skip individual inject_block calls. Reduces N+1 round trips to 1.

    IMPORTANT: when inject_all=False (default), preview text is for relevance
    filtering ONLY — truncated and incomplete. Call inject_block for every
    suggested block before applying any prior content.

    Args:
        prompt: The user's opening prompt or session description.
        session_id: Optional session identifier for deduplication.
        inject_all: If True, include full block text inline and record all
            injections immediately — no inject_block calls needed.

    Returns:
        List of Expert Prior suggestions, ranked by relevance score.
        Each item has: block_id, score, domain, intent, tags,
        context_weight, stale, preview, turn.
        Returns a single error entry if no embedding backend is configured.
    """
    sid = _effective_session_id(session_id)
    try:
        suggestions = retrieval_svc.list_suggested_blocks(
            prompt, project_root=Path.cwd(), session_id=sid, inject_all=inject_all
        )
        # UX-1: when gate passed but no priors matched, guide user to diagnose
        if not suggestions:
            from turnzero.retrieval import is_implementation_prompt
            if is_implementation_prompt(prompt, project_root=Path.cwd()):
                suggestions = [
                    SuggestionEntry(
                        block_id=BLOCK_ID_NO_MATCH_HINT,
                        score=0.0,
                        domain="system",
                        intent="review",
                        tags=["hint"],
                        context_weight=0,
                        stale=False,
                        turn="subsequent",
                        preview=(
                            "No priors matched. Run "
                            '`turnzero query --explain "<your prompt>"` to diagnose.'
                        ),
                    )
                ]
        _sentinel_ids = {BLOCK_ID_NO_MATCH_HINT, BLOCK_ID_PERSONAL_LIMIT_WARNING}
        stats_svc.log_tool_call(
            "list_suggested_blocks",
            {"prompt": prompt, "session_id": sid, "inject_all": inject_all},
            suggestions,
            meta={
                "inject_all": inject_all,
                "block_ids": [
                    s["block_id"] for s in suggestions
                    if s.get("block_id") and s["block_id"] not in _sentinel_ids
                ],
            } if inject_all else None,
        )
        return suggestions
    except RuntimeError as e:
        # Error dict uses non-SuggestionEntry keys so the client can detect the failure.
        error_payload = [
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
        stats_svc.log_tool_call("list_suggested_blocks", {"prompt": prompt}, error_payload)
        return error_payload  # type: ignore[return-value]


@mcp.tool()
def get_block(block_id: str) -> BlockData:
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
    sid = _effective_session_id(session_id)
    result = retrieval_svc.inject_block(
        block_id, session_id=sid, project_root=Path.cwd()
    )
    stats_svc.log_tool_call(
        "inject_block",
        {"block_id": block_id, "session_id": sid},
        result,
        meta={"block_id": block_id},
    )
    return result


@mcp.tool()
def get_stats() -> StatsData:
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
    sid = _effective_session_id(session_id)
    result = retrieval_svc.reset_session(sid)
    if not session_id:
        _rotate_proc_session()
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
