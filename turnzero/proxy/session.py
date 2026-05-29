"""Proxy session tracking — uuid4 IDs, 4-hour TTL, Turn 0 detection.

Session IDs are always uuid4(). Never derived from prompt content —
prompt hashes are personal data under GDPR even when truncated.
"""

from __future__ import annotations

import time
import uuid

from turnzero.config import SESSION_TTL_SECONDS

# session_id → {"started": float, "injected": bool}
_sessions: dict[str, dict[str, float | bool]] = {}


def new_session_id() -> str:
    """Generate a random session ID with no linkage to prompt content."""
    return str(uuid.uuid4())


def get_or_create(session_id: str) -> str:
    """Ensure session exists and is within TTL. Rotate if expired. Return session_id."""
    session = _sessions.get(session_id)
    if session and time.time() - float(session["started"]) > SESSION_TTL_SECONDS:
        del _sessions[session_id]
        session = None
    if not session:
        _sessions[session_id] = {"started": time.time(), "injected": False}
    return session_id


def is_turn_0(session_id: str) -> bool:
    """Return True if no injection has been recorded for this session yet."""
    return not bool(_sessions.get(session_id, {}).get("injected", False))


def mark_injected(session_id: str, blocks_count: int = 0) -> None:
    """Record that a prior injection happened for this session."""
    if session_id in _sessions:
        _sessions[session_id]["injected"] = True
        _sessions[session_id]["blocks_count"] = blocks_count


def get_blocks_count(session_id: str) -> int:
    """Return the number of blocks injected for this session (0 if unknown)."""
    return int(_sessions.get(session_id, {}).get("blocks_count", 0))


def clear(session_id: str) -> None:
    """Remove session state entirely (used in reset flows and tests)."""
    _sessions.pop(session_id, None)
