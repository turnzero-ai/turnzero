"""Harvest package — extract Expert Prior candidates from AI conversation logs.

Public API is re-exported here for backwards compatibility.
All imports of `turnzero.harvest.*` continue to work unchanged.
"""

from __future__ import annotations

from turnzero.harvest._candidates import (
    MIN_CONTEXT_WEIGHT,
    _fix_key_indentation,
    _normalise,
    content_hash,
    harvest,
    parse_candidates,
    validate_candidate,
    write_candidate,
)
from turnzero.harvest._extraction import (
    EXTRACTION_PROMPT,
    extract_with_llm,
)
from turnzero.harvest._parsers import (
    MIN_SESSION_WORDS,
    MIN_TURN_WORDS,
    convert_claude_session,
    load_conversation,
)
from turnzero.harvest._session import (
    SELF_REF_HITS_THRESHOLD,
    _discover_sessions,
    is_self_referential,
    scan_new_sessions,
)

__all__ = [
    # parsers
    "load_conversation",
    "convert_claude_session",
    "MIN_TURN_WORDS",
    "MIN_SESSION_WORDS",
    # session
    "scan_new_sessions",
    "is_self_referential",
    "SELF_REF_HITS_THRESHOLD",
    "_discover_sessions",
    # extraction
    "extract_with_llm",
    "EXTRACTION_PROMPT",
    # candidates
    "parse_candidates",
    "validate_candidate",
    "content_hash",
    "write_candidate",
    "harvest",
    "_normalise",
    "_fix_key_indentation",
    "MIN_CONTEXT_WEIGHT",
]
