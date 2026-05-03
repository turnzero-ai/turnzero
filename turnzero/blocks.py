"""Block loading, validation, and formatting."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

CONFIDENCE_REASON_MIN_LEN = 15
CONFIDENCE_MIN_CONSTRAINTS = 2
CONFIDENCE_MIN_HYPHENS = 2
MAX_AUTO_CONFIDENCE = 0.95


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
    # 0.0–1.0; curated blocks default to 1.0, AI-submitted blocks get computed score
    confidence: float = 1.0
    # curated | observed | synthetic
    verification_level: str = "curated"
    # Optional rationale for constraints (research-backed for better alignment)
    rationale: str | None = None
    # Excluded from retrieval when True; set by auto-archive after 90 days without reinforcement
    archived: bool = False
    # The storage tier this block belongs to (local, community, team, personal, etc.)
    tier: str = "unknown"
    # Optional project hash for pinning personal priors to specific projects
    project_hash: str | None = None

    @property
    def id(self) -> str:
        """Alias for slug to maintain backward compatibility where needed."""
        return self.slug

    def is_stale(self, max_age_days: int = 90) -> bool:
        verified = date.fromisoformat(self.last_verified)
        return (date.today() - verified).days > max_age_days


def compute_content_hash(data: dict[str, Any]) -> str:
    """Return the first 16 hex chars of SHA-256 of canonical YAML content.

    Excludes the `id`/`slug` and `hash` fields so the hash is stable across renames.
    """
    exclude = {"id", "slug", "hash"}
    payload = {k: v for k, v in data.items() if k not in exclude}
    canonical = yaml.dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_block(path: Path, tier: str = "unknown") -> Block:
    """Load and validate a single block YAML file."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text())

    # id is deprecated in favor of slug, but supported for now
    slug = str(raw.get("slug", raw.get("id", path.stem)))

    anti_patterns = [str(a) for a in raw.get("anti_patterns", [])]
    rationale = raw.get("rationale")

    if anti_patterns and not rationale:
        raise ValueError(
            f"Block '{slug}' has anti_patterns but is missing a 'rationale'."
        )

    return Block(
        slug=slug,
        hash=str(raw.get("hash", compute_content_hash(raw))),
        version=str(raw["version"]),
        domain=str(raw.get("domain", raw.get("stack", "unknown"))),
        intent=str(raw["intent"]),
        last_verified=str(raw["last_verified"]),
        tags=[str(t) for t in raw.get("tags", [])],
        context_weight=int(raw.get("context_weight", raw.get("token_budget", 500))),
        constraints=[str(c) for c in raw.get("constraints", [])],
        anti_patterns=anti_patterns,
        doc_anchors=[
            DocAnchor(url=str(a["url"]), verified=str(a.get("verified", "")))
            for a in raw.get("doc_anchors", [])
        ],
        conflicts_with=[str(c) for c in raw.get("conflicts_with", [])],
        conflicts_with_tags=[str(t) for t in raw.get("conflicts_with_tags", [])],
        provides=[str(p) for p in raw.get("provides", [])],
        requires=[str(r) for r in raw.get("requires", [])],
        confidence=float(raw.get("confidence", 1.0)),
        verification_level=str(raw.get("verification_level", "curated")),
        rationale=rationale,
        archived=bool(raw.get("archived", False)),
        tier=tier,
        project_hash=raw.get("project_hash"),
    )


def load_all_blocks(
    blocks_dir: Path,
    sources: list[str] | None = None,
) -> dict[str, Block]:
    """Load all *.yaml files from blocks_dir (recursive), keyed by block ID.

    If sources is given, only load from those top-level tier subdirectories
    (e.g. ['local', 'community']). None means load everything.
    """
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found: {blocks_dir}")

    blocks: dict[str, Block] = {}
    if sources is not None:
        paths: list[Path] = []
        for tier in sources:
            tier_dir = blocks_dir / tier
            if tier_dir.exists():
                paths.extend(sorted(tier_dir.rglob("*.yaml")))
    else:
        paths = sorted(blocks_dir.rglob("*.yaml"))

    for path in paths:
        rel = path.relative_to(blocks_dir)
        tier = rel.parts[0] if len(rel.parts) > 1 else "unknown"
        block = load_block(path, tier=tier)
        blocks[block.id] = block

    return blocks
