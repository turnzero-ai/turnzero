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

    @property
    def id(self) -> str:
        """Alias for slug to maintain backward compatibility where needed."""
        return self.slug

    def is_stale(self, max_age_days: int = 90) -> bool:
        verified = date.fromisoformat(self.last_verified)
        return (date.today() - verified).days > max_age_days

    def to_search_text(self) -> str:
        """Text representation used when embedding this block into the index.

        Phrased as a natural-language query matching how users open AI sessions.
        Intent-aware framing: build=imperative, debug=problem statement,
        migrate=transition language, review=evaluation request.
        """
        tag_str = " ".join(self.tags)

        intent_prefix = {
            "build": f"build a {self.domain} {tag_str} project",
            "debug": f"fix {self.domain} {tag_str} error or problem",
            "migrate": f"migrate or upgrade {self.domain} {tag_str} project",
            "review": f"review or check {self.domain} {tag_str} code",
        }.get(self.intent, f"{self.intent} {self.domain} {tag_str}")

        # Use first anti-pattern for debug (sounds like a problem), constraint otherwise
        if self.intent == "debug" and self.anti_patterns:
            hint = self.anti_patterns[0].split(".")[0][:100]
        elif self.constraints:
            hint = self.constraints[0].split(".")[0][:100]
        else:
            return intent_prefix

        return f"{intent_prefix}: {hint}"

    def to_injection_text(self) -> str:
        """Formatted Expert Prior ready to inject into an AI session.
        
        Uses a hierarchical structure (Identity -> Constraints -> Task) 
        to maximize LLM anchoring based on research (Ni, 2026).
        """
        domain_title = self.domain.replace("-", " ").title()
        role = f"Expert {domain_title} {self.intent.title()} Assistant"
        
        lines: list[str] = [
            "# EXPERT_PRIOR_IDENTITY",
            f"Role: {role}",
            f"Slug: {self.slug} (v{self.version})",
            "",
            "# SESSION_CONSTRAINTS",
        ]
        
        if self.constraints:
            for c in self.constraints:
                lines.append(f"- {c}")
        
        if self.anti_patterns:
            lines.append("")
            lines.append("# ANTI_PATTERNS")
            for a in self.anti_patterns:
                # Ensure every anti-pattern starts with "Do not" as per mandate
                prefix = "" if a.lower().startswith("do not") else "Do not: "
                lines.append(f"- {prefix}{a}")

        lines.extend([
            "",
            "# VALIDATION_TASK",
            f"Prioritize the constraints and anti-patterns above for the duration of this {self.domain} {self.intent} session.",
        ])

        if self.doc_anchors:
            lines.append("")
            lines.append("# REFERENCE_DOCS")
            for anchor in self.doc_anchors:
                lines.append(f"- {anchor.url}")
                
        return "\n".join(lines)


def compute_content_hash(data: dict[str, Any]) -> str:
    """Return the first 16 hex chars of SHA-256 of canonical YAML content.

    Excludes the `id`/`slug` and `hash` fields so the hash is stable across renames.
    """
    exclude = {"id", "slug", "hash"}
    payload = {k: v for k, v in data.items() if k not in exclude}
    canonical = yaml.dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_block(path: Path) -> Block:
    """Load and validate a single block YAML file."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text())

    # id is deprecated in favor of slug, but supported for now
    slug = str(raw.get("slug", raw.get("id", path.stem)))

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
        anti_patterns=[str(a) for a in raw.get("anti_patterns", [])],
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
        rationale=raw.get("rationale"),
        archived=bool(raw.get("archived", False)),
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
        block = load_block(path)
        blocks[block.id] = block

    return blocks
