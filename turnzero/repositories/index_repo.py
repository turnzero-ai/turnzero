"""Index repository — all file I/O for building, loading, and updating the block index."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from turnzero.embed import embed, get_model_id
from turnzero.formatters import block_fmt
from turnzero.repositories.block_repo import load_all_blocks, load_block


@dataclass(frozen=True)
class IndexHeader:
    """Header line for index files to ensure model compatibility."""

    model_id: str
    built_at: str
    version: str = "1"


# ---------------------------------------------------------------------------
# IndexEntry — lives here because it's a direct product of index loading
# ---------------------------------------------------------------------------


@dataclass
class IndexEntry:
    block_id: str
    embedding: np.ndarray
    domain: str
    intent: str
    tags: list[str]
    source: str = "local"


# ---------------------------------------------------------------------------
# I/O operations
# ---------------------------------------------------------------------------


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

    by_source: dict[str, list[str]] = defaultdict(list)
    model_id = get_model_id()
    header = IndexHeader(
        model_id=model_id,
        built_at=datetime.now().isoformat(timespec="seconds"),
    )
    header_json = json.dumps({"header": asdict(header)})

    # Write to temp file first — swap on full success to avoid corrupt live index.
    tmp_path = index_path.with_suffix(".tmp")
    try:
        with tmp_path.open("w") as merged:
            merged.write(header_json + "\n")
            for path in paths:
                rel = path.relative_to(blocks_dir)
                source = rel.parts[0] if len(rel.parts) > 1 else "local"
                block = load_block(path, tier=source)
                embedding = embed(block_fmt.to_search_text(block))
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
    return [b for b, block in blocks.items() if block.is_stale(max_age_days)]


def load_index(
    index_path: Path,
    sources: list[str] | None = None,
) -> list[IndexEntry]:
    """Load index.jsonl, returning IndexEntry objects.

    If sources is given, only return entries whose source tier is in the list.
    """
    if not index_path.exists():
        raise FileNotFoundError(
            f"Index not found at {index_path}\nBuild it first:  turnzero index build"
        )

    entries: list[IndexEntry] = []
    current_model = get_model_id()

    for line in index_path.read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)

        if "header" in data:
            built_model = data["header"].get("model_id")
            if built_model and built_model != current_model:
                try:
                    from rich.console import Console

                    console = Console(stderr=True)
                    console.print(
                        f"\n[bold yellow]⚠[/bold yellow] [yellow]Index model mismatch:[/yellow]\n"
                        f"  Built with: [cyan]{built_model}[/cyan]\n"
                        f"  Current:    [cyan]{current_model}[/cyan]\n"
                        f"  Retrieval scores may be inaccurate. Re-build: [bold]turnzero index build[/bold]\n"
                    )
                except ImportError:
                    print(
                        f"\nWARNING: Index model mismatch (built with {built_model}, using {current_model}).\n"
                        "Retrieval scores may be inaccurate. Re-build: turnzero index build\n",
                        file=sys.stderr,
                    )
            continue

        source = data.get("source", "local")
        if sources is not None and source not in sources:
            continue
        entries.append(
            IndexEntry(
                block_id=data["block_id"],
                embedding=np.array(data["embedding"], dtype=np.float32),
                domain=data.get("domain", data.get("stack", "unknown")),
                intent=data["intent"],
                tags=data["tags"],
                source=source,
            )
        )
    return entries


def append_block(
    block_path: Path,
    tier: str,
    index_path: Path,
    data_dir: Path,
) -> None:
    """Append a single new block to the merged index and its per-source index.

    Falls back to a full rebuild if the append fails for any reason.
    """
    try:
        new_block = load_block(block_path, tier=tier)
        embedding = embed(block_fmt.to_search_text(new_block))
        line = json.dumps(
            {
                "block_id": new_block.slug,
                "embedding": embedding.tolist(),
                "domain": new_block.domain,
                "intent": new_block.intent,
                "tags": new_block.tags,
                "source": new_block.tier,
            }
        )

        with open(index_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        tier_index_path = data_dir / f"index_{tier}.jsonl"
        if tier_index_path.exists():
            with open(tier_index_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            # Per-source index doesn't exist yet — full rebuild creates it
            from turnzero.config import get_blocks_dir

            build(get_blocks_dir(), index_path, data_dir=data_dir)
    except Exception:
        from turnzero.config import get_blocks_dir

        build(get_blocks_dir(), index_path, data_dir=data_dir)
