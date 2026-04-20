"""Build and verify the block embedding index."""

from __future__ import annotations

import json
from pathlib import Path

from turnzero.blocks import Block, load_all_blocks, load_block
from turnzero.embed import embed


def build(blocks_dir: Path, index_path: Path) -> int:
    """Embed all blocks and write index.jsonl.

    Each block is represented by the text from block.to_search_text().
    Derives the source tier from the first subdirectory level under blocks_dir.
    Returns the number of blocks indexed.
    """
    if not blocks_dir.exists():
        raise ValueError(f"Blocks directory not found: {blocks_dir}")

    paths = sorted(blocks_dir.rglob("*.yaml"))
    if not paths:
        raise ValueError(f"No blocks found in {blocks_dir}")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with index_path.open("w") as f:
        for path in paths:
            block = load_block(path)
            rel = path.relative_to(blocks_dir)
            source = rel.parts[0] if len(rel.parts) > 1 else "local"
            search_text = block.to_search_text()
            embedding = embed(search_text)
            entry = {
                "block_id": block.slug,
                "embedding": embedding.tolist(),
                "domain": block.domain,
                "intent": block.intent,
                "tags": block.tags,
                "source": source,
            }
            f.write(json.dumps(entry) + "\n")
            count += 1

    return count


def verify(blocks_dir: Path, max_age_days: int = 90) -> list[str]:
    """Return IDs of blocks not verified within max_age_days."""
    blocks = load_all_blocks(blocks_dir)
    return [
        block_id
        for block_id, block in blocks.items()
        if block.is_stale(max_age_days)
    ]
