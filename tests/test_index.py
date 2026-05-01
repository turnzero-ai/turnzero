"""Tests for index.py — atomic write and failure safety."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from turnzero.embed import EMBEDDING_DIM


def _fake_block_yaml(slug: str) -> str:
    return f"""slug: {slug}
version: 1.0.0
domain: fastapi
intent: build
tier: local
last_verified: '2026-01-01'
verification_level: curated
confidence: 1.0
context_weight: 100
tags: []
provides: []
conflicts_with_tags: []
conflicts_with: []
requires: []
constraints:
- Use async def for endpoints.
anti_patterns:
- Do not block the event loop.
rationale: Test block.
"""


def _fake_embedding() -> list[float]:
    return [0.1] * EMBEDDING_DIM


def test_build_writes_valid_index(tmp_path: Path) -> None:
    blocks_dir = tmp_path / "blocks" / "local"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "test-block.yaml").write_text(_fake_block_yaml("test-block"))

    index_path = tmp_path / "index.jsonl"

    with patch(
        "turnzero.index.embed",
        return_value=np.array(_fake_embedding(), dtype=np.float32),
    ):
        from turnzero.index import build

        count = build(tmp_path / "blocks", index_path, data_dir=tmp_path)

    assert count == 1
    assert index_path.exists()
    lines = index_path.read_text().splitlines()
    header = json.loads(lines[0])
    assert "header" in header
    entry = json.loads(lines[1])
    assert entry["block_id"] == "test-block"


def test_build_no_tmp_file_left_on_success(tmp_path: Path) -> None:
    blocks_dir = tmp_path / "blocks" / "local"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "test-block.yaml").write_text(_fake_block_yaml("test-block"))

    index_path = tmp_path / "index.jsonl"
    tmp_file = index_path.with_suffix(".tmp")

    with patch(
        "turnzero.index.embed",
        return_value=np.array(_fake_embedding(), dtype=np.float32),
    ):
        from turnzero.index import build

        build(tmp_path / "blocks", index_path, data_dir=tmp_path)

    assert not tmp_file.exists()


def test_build_leaves_old_index_intact_on_embed_failure(tmp_path: Path) -> None:
    blocks_dir = tmp_path / "blocks" / "local"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "test-block.yaml").write_text(_fake_block_yaml("test-block"))

    index_path = tmp_path / "index.jsonl"
    original_content = "original index content\n"
    index_path.write_text(original_content)

    with (
        patch("turnzero.index.embed", side_effect=RuntimeError("ollama timeout")),
        pytest.raises(RuntimeError, match="ollama timeout"),
    ):
        from turnzero.index import build

        build(tmp_path / "blocks", index_path, data_dir=tmp_path)

    # Old index must be untouched
    assert index_path.read_text() == original_content
    # Tmp file must be cleaned up
    assert not (index_path.with_suffix(".tmp")).exists()


def test_build_no_blocks_raises(tmp_path: Path) -> None:
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    index_path = tmp_path / "index.jsonl"

    with pytest.raises(ValueError, match="No blocks found"):
        from turnzero.index import build

        build(blocks_dir, index_path)
