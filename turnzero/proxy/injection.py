"""Prior injection — pull priors and prepend to system message. Always fail-open."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from turnzero.proxy import session as proxy_session
from turnzero.services import retrieval_svc
from turnzero.types import BLOCK_ID_SENTINELS


def extract_prompt(messages: list[dict[str, Any]]) -> str:
    """Return the last user message content as plain text."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
    return ""


_CLIENT_MARKER_PATTERNS = ("BEGIN_ARG", "END_ARG", "<context>", "<file_contents>")


def _has_client_markers(content: object) -> bool:
    """Return True if content contains client-injected context markers (e.g. Continue's @codebase)."""
    text = content if isinstance(content, str) else str(content)
    return any(m in text for m in _CLIENT_MARKER_PATTERNS)


def _prepend_to_system(
    messages: list[dict[str, Any]], prefix: str
) -> list[dict[str, Any]]:
    """Append priors to existing system message, or insert one if absent.

    Skips modification when the system message contains client context markers
    (e.g. Continue's BEGIN_ARG/END_ARG from @codebase) — those markers break
    if combined with injected text and cause Gemini to echo them back.
    """
    messages = [dict(m) for m in messages]
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            existing = msg.get("content", "")
            if _has_client_markers(existing):
                # Can't safely merge — client markers (e.g. Continue's @codebase BEGIN_ARG/END_ARG)
                # break when combined with injected text. Skip injection for this request.
                return messages
            messages[i] = {**msg, "content": f"{existing}\n\n{prefix}".strip()}
            return messages
    return [{"role": "system", "content": prefix}, *messages]


def maybe_inject(
    messages: list[dict[str, Any]],
    session_id: str,
    project_root_str: str | None = None,
) -> list[dict[str, Any]]:
    """Inject relevant priors into system message at Turn 0. Fail-open on any error.

    Uses inject_all=True (WF-3 batch path) — one retrieval_svc call, no N+1 round trips.
    On any exception (embedding down, index missing, etc.) returns messages unchanged.
    """
    if not proxy_session.is_turn_0(session_id):
        return messages

    try:
        project_root = Path(project_root_str) if project_root_str else None
        prompt = extract_prompt(messages)
        suggestions = retrieval_svc.list_suggested_blocks(
            prompt,
            inject_all=True,
            session_id=session_id,
            project_root=project_root,
        )
        injectable = [
            s for s in suggestions
            if s.get("full_text") and s.get("block_id") not in BLOCK_ID_SENTINELS
        ]
        if injectable:
            prior_text = "\n\n".join(s["full_text"] for s in injectable)
            messages = _prepend_to_system(messages, prior_text)
            proxy_session.mark_injected(session_id, blocks_count=len(injectable))
    except Exception:
        pass

    return messages
