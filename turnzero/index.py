"""Build and verify the block embedding index."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from turnzero.formatters import block_fmt
from turnzero.repositories.block_repo import load_all_blocks, load_block
from turnzero.embed import embed, get_model_id


@dataclass(frozen=True)
class IndexHeader:
    """Header line for index files to ensure model compatibility."""

    model_id: str
    built_at: str
    version: str = "1"


def build(blocks_dir: Path, index_path: Path, data_dir: Path | None = None) -> int:
    """Embed all blocks and write index.jsonl (merged) plus per-source index files.

    If data_dir is provided, also writes index_{source}.jsonl for each source
    tier found — enabling cheap registry sync and per-source caching.
    Returns the number of blocks indexed.
    """
    if not blocks_dir.exists():
        raise ValueError(f"Blocks directory not found: {blocks_dir}")

    paths = sorted(blocks_dir.rglob("*.yaml"))
    if not paths:
        raise ValueError(f"No blocks found in {blocks_dir}")

    index_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect entries grouped by source for per-source files
    by_source: dict[str, list[str]] = defaultdict(list)
    model_id = get_model_id()
    header = IndexHeader(
        model_id=model_id,
        built_at=datetime.now().isoformat(timespec="seconds"),
    )
    header_json = json.dumps({"header": asdict(header)})

    # Write to a temp file first — swap to final path only on full success.
    # Prevents a failed/timed-out embedding run from corrupting the live index.
    tmp_path = index_path.with_suffix(".tmp")
    try:
        with tmp_path.open("w") as merged:
            merged.write(header_json + "\n")
            for path in paths:
                rel = path.relative_to(blocks_dir)
                source = rel.parts[0] if len(rel.parts) > 1 else "local"
                block = load_block(path, tier=source)
                search_text = block_fmt.to_search_text(block)
                embedding = embed(search_text)
                line = json.dumps(
                    {
                        "block_id": block.slug,
                        "embedding": embedding.tolist(),
                        "domain": block.domain,
                        "intent": block.intent,
                        "tags": block.tags,
                        "source": block.tier,
                    }
                )
                merged.write(line + "\n")
                by_source[source].append(line)
        os.replace(tmp_path, index_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # Write per-source index files atomically when data_dir is available
    if data_dir is not None:
        for source, lines in by_source.items():
            source_path = data_dir / f"index_{source}.jsonl"
            tmp_source = source_path.with_suffix(".tmp")
            try:
                tmp_source.write_text(header_json + "\n" + "\n".join(lines) + "\n")
                os.replace(tmp_source, source_path)
            except Exception:
                tmp_source.unlink(missing_ok=True)
                raise

    return sum(len(v) for v in by_source.values())


def verify(blocks_dir: Path, max_age_days: int = 90) -> list[str]:
    """Return IDs of blocks not verified within max_age_days."""
    blocks = load_all_blocks(blocks_dir)
    return [
        block_id for block_id, block in blocks.items() if block.is_stale(max_age_days)
    ]
