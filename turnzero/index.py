"""Build and verify the block embedding index."""

from __future__ import annotations

import json
from pathlib import Path

from turnzero.blocks import Block, load_all_blocks
from turnzero.embed import embed


def build(blocks_dir: Path, index_path: Path) -> int:
    """Embed all blocks and write index.jsonl.

    Each block is represented by the text from block.to_search_text().
    Returns the number of blocks indexed.
    """
    blocks: dict[str, Block] = load_all_blocks(blocks_dir)
    if not blocks:
        raise ValueError(f"No blocks found in {blocks_dir}")

    index_path.parent.mkdir(parents=True, exist_ok=True)

    with index_path.open("w") as f:
        for block in blocks.values():
            search_text = block.to_search_text()
            embedding = embed(search_text)
            entry = {
                "block_id": block.slug,
                "embedding": embedding.tolist(),
                "domain": block.domain,
                "intent": block.intent,
                "tags": block.tags,
            }
            f.write(json.dumps(entry) + "\n")

    return len(blocks)


def verify(blocks_dir: Path, max_age_days: int = 90) -> list[str]:
    """Return IDs of blocks not verified within max_age_days."""
    blocks = load_all_blocks(blocks_dir)
    return [
        block_id
        for block_id, block in blocks.items()
        if block.is_stale(max_age_days)
    ]
