"""Block repository — all file I/O for loading blocks from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from turnzero.blocks import Block, DocAnchor, compute_content_hash


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


def update_fields(path: Path, **kwargs: Any) -> None:
    """Read a block YAML, merge kwargs into it, and write atomically."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.update(kwargs)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(path)


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
