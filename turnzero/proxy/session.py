"""Proxy session tracking — uuid4 IDs, 4-hour TTL, Turn 0 detection.

Session IDs are always uuid4(). Never derived from prompt content —
prompt hashes are personal data under GDPR even when truncated.
"""

from __future__ import annotations

import time
import uuid

_SESSION_TTL: float = 4 * 3600.0

# session_id → {"started": float, "injected": bool}
_sessions: dict[str, dict[str, float | bool]] = {}


def new_session_id() -> str:
    """Generate a random session ID with no linkage to prompt content."""
    return str(uuid.uuid4())


def get_or_create(session_id: str) -> str:
    """Ensure session exists and is within TTL. Rotate if expired. Return session_id."""
    session = _sessions.get(session_id)
    if session and time.time() - float(session["started"]) > _SESSION_TTL:
        del _sessions[session_id]
        session = None
    if not session:
        _sessions[session_id] = {"started": time.time(), "injected": False}
    return session_id


def is_turn_0(session_id: str) -> bool:
    """Return True if no injection has been recorded for this session yet."""
    return not bool(_sessions.get(session_id, {}).get("injected", False))


def mark_injected(session_id: str) -> None:
    """Record that a prior injection happened for this session."""
    if session_id in _sessions:
        _sessions[session_id]["injected"] = True


def clear(session_id: str) -> None:
    """Remove session state entirely (used in reset flows and tests)."""
    _sessions.pop(session_id, None)
