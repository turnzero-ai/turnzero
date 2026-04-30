"""Tests for bundled package data resolution."""

from __future__ import annotations

from pathlib import Path

from turnzero.config import _bundled_blocks_dir, _bundled_index_path


def test_bundled_paths_resolve_to_repo_data():
    # When running from the repo root, these should point to the data/ directory
    repo_root = Path(__file__).parent.parent

    index_path = _bundled_index_path()
    blocks_dir = _bundled_blocks_dir()

    assert index_path.exists()
    assert index_path == repo_root / "data" / "index.jsonl"

    assert blocks_dir.exists()
    assert blocks_dir == repo_root / "data" / "blocks"


def test_config_helpers_match_cli_helpers():
    from turnzero.cli.base import _bundled_index_path as cli_bundled_index
    from turnzero.config import _bundled_index_path as config_bundled_index

    assert cli_bundled_index() == config_bundled_index()
