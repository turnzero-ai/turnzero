"""Block domain model — pure data, no I/O."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_REASON_MIN_LEN = 15
CONFIDENCE_MIN_CONSTRAINTS = 2
CONFIDENCE_MIN_HYPHENS = 2
MAX_AUTO_CONFIDENCE = 0.95


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass
class DocAnchor:
    url: str
    verified: str


@dataclass
class Block:
    slug: str
    hash: str
    version: str
    domain: str
    intent: str  # build | debug | migrate | review
    last_verified: str
    tags: list[str]
    context_weight: int
    constraints: list[str]
    anti_patterns: list[str]
    doc_anchors: list[DocAnchor]
    conflicts_with: list[str] = field(default_factory=list)
    conflicts_with_tags: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    confidence: float = 1.0
    verification_level: str = "curated"
    rationale: str | None = None
    archived: bool = False
    tier: str = "unknown"
    project_hash: str | None = None

    @property
    def id(self) -> str:
        return self.slug

    def is_stale(self, max_age_days: int = 90) -> bool:
        verified = date.fromisoformat(self.last_verified)
        return (date.today() - verified).days > max_age_days


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def compute_confidence(
    slug: str,
    constraints: list[str],
    anti_patterns: list[str],
    tags: list[str],
    reason: str | None = None,
) -> float:
    """Score block quality based on content density and context signals.

    Signals: non-empty reason, constraint count, anti-pattern presence,
    tags, and slug specificity (hyphen count as specificity proxy).
    Cap at 0.95 — only manually curated blocks reach 1.0.
    """
    score = 0.25
    if reason and len(reason.strip()) >= CONFIDENCE_REASON_MIN_LEN:
        score += 0.20
    if len(constraints) >= CONFIDENCE_MIN_CONSTRAINTS:
        score += 0.20
    if anti_patterns:
        score += 0.15
    if tags:
        score += 0.10
    if slug.count("-") >= CONFIDENCE_MIN_HYPHENS:
        score += 0.10
    return round(min(score, MAX_AUTO_CONFIDENCE), 2)


def compute_content_hash(data: dict[str, Any]) -> str:
    """Return the first 16 hex chars of SHA-256 of canonical YAML content.

    Excludes the `id`/`slug` and `hash` fields so the hash is stable across renames.
    """
    exclude = {"id", "slug", "hash"}
    payload = {k: v for k, v in data.items() if k not in exclude}
    canonical = yaml.dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
