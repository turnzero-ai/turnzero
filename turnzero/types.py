"""Shared types, enums, and constants for TurnZero.

TypedDicts document the shape of dict returns at service/MCP boundaries.
StrEnums replace raw string literals for categoricals that appear across
multiple modules — rename in one place, catch mismatches at type-check time.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Tier(StrEnum):
    """Block source tier. Compares equal to the equivalent plain string."""
    PERSONAL = "personal"
    COMMUNITY = "community"
    LOCAL = "local"
    TEAM = "team"


class Intent(StrEnum):
    """Block intent category."""
    BUILD = "build"
    DEBUG = "debug"
    MIGRATE = "migrate"
    REVIEW = "review"


class TurnLabel(StrEnum):
    """Injection turn within a session."""
    FIRST = "first"
    SUBSEQUENT = "subsequent"


class TelemetryEvent(StrEnum):
    """PostHog event names — update here, propagates everywhere."""
    SESSION_START = "session_start"
    BLOCK_INJECTED = "block_injected"
    CANDIDATE_SUBMITTED = "candidate_submitted"
    SESSION_SUMMARY = "session_summary"
    SETUP_COMPLETED = "setup_completed"
    REVIEW_OPENED = "review_opened"
    STATS_VIEWED = "stats_viewed"
    LIST_VIEWED = "list_viewed"
    DOMAIN_CHANGED = "domain_changed"


# ---------------------------------------------------------------------------
# MCP tool name constants
# ---------------------------------------------------------------------------

TOOL_LIST_SUGGESTED = "list_suggested_blocks"
TOOL_INJECT_BLOCK = "inject_block"
TOOL_GET_BLOCK = "get_block"
TOOL_SUBMIT_CANDIDATE = "submit_candidate"
TOOL_GET_STATS = "get_stats"
TOOL_RESET_SESSION = "reset_session"
TOOL_LEARN_FROM_SESSION = "learn_from_session"

# Set of tools whose token cost counts as "injection overhead"
INJECTION_TOOLS: frozenset[str] = frozenset({TOOL_LIST_SUGGESTED, TOOL_INJECT_BLOCK})

# ---------------------------------------------------------------------------
# Special block ID sentinels
# ---------------------------------------------------------------------------

BLOCK_ID_NO_MATCH_HINT = "no-match-hint"
BLOCK_ID_PERSONAL_LIMIT_WARNING = "personal-priors-limit-warning"


# ---------------------------------------------------------------------------
# TypedDicts — MCP / service boundary shapes
# ---------------------------------------------------------------------------


class DocAnchorData(TypedDict):
    url: str
    verified: str


class SuggestionEntry(TypedDict, total=False):
    """One entry returned by list_suggested_blocks.

    Required fields are always present. ``full_text`` is only present when
    ``inject_all=True`` was passed. Sentinel entries (no-match-hint,
    personal-priors-limit-warning) share this shape with subset of fields.
    """
    # Required
    block_id: str
    score: float
    domain: str
    intent: str
    tags: list[str]
    context_weight: int
    stale: bool
    turn: str
    preview: str
    # Optional — only when inject_all=True
    full_text: str


class BlockData(TypedDict):
    """Full block data as returned by get_block."""
    id: str
    slug: str
    hash: str
    version: str
    domain: str
    intent: str
    last_verified: str
    stale: bool
    tags: list[str]
    context_weight: int
    provides: list[str]
    conflicts_with_tags: list[str]
    constraints: list[str]
    anti_patterns: list[str]
    doc_anchors: list[DocAnchorData]
    conflicts_with: list[str]
    requires: list[str]
    active: bool


class LibraryStats(TypedDict):
    total_blocks: int
    personal_blocks: int
    expert_blocks: int
    stale_blocks: int
    candidates_pending_review: int


class CountWithWeek(TypedDict):
    total: int
    this_week: int


class TokenCostStats(TypedDict):
    total_in: int
    total_out: int
    total: int
    this_week: int
    submit_candidate_total: int


class StatsData(TypedDict):
    """Shape of stats_svc.compute() return value."""
    sessions: CountWithWeek
    priors_injected: CountWithWeek
    context_tokens_injected: dict[str, Any]
    injection_overhead: dict[str, Any]
    estimated_turns_saved: int
    estimated_tokens_saved: int
    top_domains: list[str]
    top_blocks: list[dict[str, Any]]
    library: LibraryStats
    tool_calls: dict[str, Any]
    token_cost: TokenCostStats
