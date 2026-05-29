"""Prior injection — pull priors and prepend to system message. Always fail-open."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from turnzero.proxy import session as proxy_session
from turnzero.services import retrieval_svc
from turnzero.types import BLOCK_ID_SENTINELS


def _extract_prompt(messages: list[dict[str, Any]]) -> str:
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


def _prepend_to_system(
    messages: list[dict[str, Any]], prefix: str
) -> list[dict[str, Any]]:
    """Prepend prefix to existing system message, or insert one if absent."""
    messages = [dict(m) for m in messages]
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            existing = msg.get("content", "")
            messages[i] = {**msg, "content": f"{prefix}\n\n{existing}".strip()}
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
        prompt = _extract_prompt(messages)
        suggestions = retrieval_svc.list_suggested_blocks(
            prompt,
            inject_all=True,
            session_id=session_id,
            project_root=project_root,
        )
        prior_text = "\n\n".join(
            s["full_text"]
            for s in suggestions
            if s.get("full_text") and s.get("block_id") not in BLOCK_ID_SENTINELS
        )
        if prior_text:
            messages = _prepend_to_system(messages, prior_text)
            blocks_count = sum(
                1 for s in suggestions
                if s.get("full_text") and s.get("block_id") not in BLOCK_ID_SENTINELS
            )
            proxy_session.mark_injected(session_id, blocks_count=blocks_count)
    except Exception:
        pass

    return messages
