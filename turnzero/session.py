"""Session lifecycle — single owner for all session state and project affinity.

All callers must import from here, not from state directly. state.py contains
the raw I/O implementations; SessionLifecycle is the authoritative interface.
"""

from __future__ import annotations

from turnzero.state import (
    _get_project_hash,
    clear_session_injections,
    get_project_affinity,
    get_session_injections,
    record_project_affinity,
    record_session_injection,
)

__all__ = [
    "SessionLifecycle",
    "_get_project_hash",
    "clear_session_injections",
    "get_project_affinity",
    "get_session_injections",
    "record_project_affinity",
    "record_session_injection",
]


class SessionLifecycle:
    """Namespace that owns all session state — injections, affinity, project hashing.

    All methods are static; there is no per-instance state. The on-disk state
    lives in the data directory controlled by config.get_data_dir().
    """

    get_project_hash = staticmethod(_get_project_hash)
    get_session_injections = staticmethod(get_session_injections)
    record_session_injection = staticmethod(record_session_injection)
    clear_session_injections = staticmethod(clear_session_injections)
    get_project_affinity = staticmethod(get_project_affinity)
    record_project_affinity = staticmethod(record_project_affinity)
