"""Tests for Session Deduplication and Project Affinity."""

from __future__ import annotations

from pathlib import Path

from turnzero.blocks import Block
from turnzero.retrieval import IndexEntry, query
from turnzero.state import (
    get_session_injections,
    record_project_affinity,
    record_session_injection,
)


def test_session_deduplication(tmp_path: Path):
    # Mock data dir
    from unittest.mock import patch

    data_dir = tmp_path / "turnzero"
    session_id = "test-session"
    block_id = "fastapi-async-build"

    with patch("turnzero.config._data_dir", return_value=data_dir):
        # 1. Record injection
        record_session_injection(session_id, block_id)

        # 2. Verify it's tracked
        injections = get_session_injections(session_id)
        assert block_id in injections

        # 3. Verify query excludes it
        index = [
            IndexEntry(
                block_id=block_id,
                embedding=[0.1] * 768,
                domain="fastapi",
                intent="build",
                tags=["fastapi"],
                source="local",
            )
        ]
        blocks = {
            block_id: Block(
                slug=block_id,
                hash="h",
                version="1",
                domain="fastapi",
                intent="build",
                last_verified="2026",
                tags=["fastapi"],
                context_weight=100,
                constraints=[],
                anti_patterns=[],
                doc_anchors=[],
            )
        }

        results = query("build fastapi", index, blocks, exclude_block_ids=injections)
        assert len(results) == 0


def test_project_affinity_boosting(tmp_path: Path):
    from unittest.mock import patch

    data_dir = tmp_path / "turnzero"
    project_root = tmp_path / "my-project"
    project_root.mkdir()
    block_id = "fastapi-async-build"

    with patch("turnzero.config._data_dir", return_value=data_dir):
        # 1. Record affinity
        record_project_affinity(project_root, block_id)

        # 2. Verify boost is applied in query
        index = [
            IndexEntry(
                block_id=block_id,
                embedding=[0.1] * 768,
                domain="fastapi",
                intent="build",
                tags=["fastapi"],
                source="local",
            )
        ]
        blocks = {
            block_id: Block(
                slug=block_id,
                hash="h",
                version="1",
                domain="fastapi",
                intent="build",
                last_verified="2026",
                tags=["fastapi"],
                context_weight=100,
                constraints=[],
                anti_patterns=[],
                doc_anchors=[],
            )
        }

        # Query with low score but affinity should boost it
        # We'll mock cosine_similarity to return 0.70 (barely at threshold)
        with patch("turnzero.retrieval.cosine_similarity", return_value=0.70):
            results = query(
                "fastapi", index, blocks, project_root=project_root, threshold=0.75
            )
            # 0.70 * 1.15 (affinity) = 0.805 -> above 0.75 threshold
            assert len(results) == 1
            assert results[0][0].slug == block_id
