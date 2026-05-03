"""Unit tests for the retrieval service layer."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from turnzero.blocks import Block
from turnzero.services import retrieval_svc


@pytest.fixture
def mock_blocks_1() -> dict[str, Block]:
    return {
        "test-block-1": Block(
            slug="test-block-1",
            hash="hash1",
            version="1.0.0",
            domain="test",
            intent="build",
            last_verified="2026-01-01",
            tags=[],
            context_weight=100,
            constraints=["Constraint 1"],
            anti_patterns=[],
            doc_anchors=[],
            tier="local",
        )
    }


@pytest.fixture
def mock_blocks_2() -> dict[str, Block]:
    return {
        "test-block-1": Block(
            slug="test-block-1",
            hash="hash2",  # Different hash to distinguish from mock_blocks_1
            version="1.0.1",
            domain="test",
            intent="build",
            last_verified="2026-01-02",
            tags=[],
            context_weight=100,
            constraints=["Constraint 1 Updated"],
            anti_patterns=[],
            doc_anchors=[],
            tier="local",
        )
    }


def test_block_cache_invalidation(tmp_path: Path, mock_blocks_1: dict[str, Block], mock_blocks_2: dict[str, Block]) -> None:
    """Verify that the block cache invalidates when a file mtime changes."""
    blocks_dir = tmp_path / "blocks"
    local_dir = blocks_dir / "local" / "test"
    local_dir.mkdir(parents=True)
    block_file = local_dir / "test-block-1.yaml"
    block_file.write_text("slug: test-block-1\nversion: 1.0.0\nintent: build\nlast_verified: '2026-01-01'", encoding="utf-8")

    # Clear cache before starting
    retrieval_svc._BLOCKS_CACHE.clear()

    with patch("turnzero.services.retrieval_svc.get_blocks_dir", return_value=blocks_dir), \
         patch("turnzero.services.retrieval_svc.enabled_sources", return_value=["local"]), \
         patch("turnzero.services.retrieval_svc.load_all_blocks") as mock_load:
        
        # Setup mock to return different data on successive calls
        mock_load.side_effect = [mock_blocks_1, mock_blocks_2]
        
        # First load - should hit disk
        blocks1 = retrieval_svc._load_active_blocks()
        assert blocks1["test-block-1"].hash == "hash1"
        assert mock_load.call_count == 1

        # Second load - should hit cache
        blocks2 = retrieval_svc._load_active_blocks()
        assert blocks2["test-block-1"].hash == "hash1"
        assert blocks2 is blocks1
        assert mock_load.call_count == 1

        # Modify mtime - should invalidate and hit disk
        new_mtime = time.time() + 100
        os.utime(block_file, (new_mtime, new_mtime))
        
        blocks3 = retrieval_svc._load_active_blocks()
        assert mock_load.call_count == 2
        assert blocks3["test-block-1"].hash == "hash2"
        assert blocks3 is not blocks1
