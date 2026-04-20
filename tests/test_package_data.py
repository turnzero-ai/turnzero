"""Verify that bundled block data is discoverable via the path resolution used at runtime.

This test must pass both in dev mode (pip install -e .) and from an installed wheel.
The resolution mirrors what turnzero setup and the CLI use:
  1. Package-relative path: <package>/data/blocks  (pip install wheel)
  2. Repo-relative fallback: <repo-root>/data/blocks  (pip install -e .)
"""

from __future__ import annotations

from pathlib import Path

import turnzero
from turnzero.blocks import load_all_blocks


def _bundled_blocks_dir() -> Path:
    pkg_root = Path(turnzero.__file__).parent
    pkg_blocks = pkg_root / "data" / "blocks"
    if pkg_blocks.exists():
        return pkg_blocks
    repo_blocks = pkg_root.parent / "data" / "blocks"
    if repo_blocks.exists():
        return repo_blocks
    raise FileNotFoundError(
        f"Bundled blocks not found at {pkg_blocks} or {repo_blocks}. "
        "Run 'pip install -e .' from the repo root, or rebuild the wheel."
    )


def test_bundled_blocks_dir_is_reachable() -> None:
    blocks_dir = _bundled_blocks_dir()
    assert blocks_dir.is_dir(), f"Expected a directory at {blocks_dir}"


def test_bundled_blocks_dir_has_yaml_files() -> None:
    blocks_dir = _bundled_blocks_dir()
    yaml_files = list(blocks_dir.rglob("*.yaml"))
    assert len(yaml_files) >= 8, (
        f"Expected at least 8 YAML blocks in {blocks_dir}, found {len(yaml_files)}"
    )


def test_bundled_blocks_load_without_error() -> None:
    blocks_dir = _bundled_blocks_dir()
    blocks = load_all_blocks(blocks_dir)
    assert len(blocks) >= 8, f"Expected at least 8 loaded blocks, got {len(blocks)}"


def test_bundled_blocks_all_valid() -> None:
    blocks_dir = _bundled_blocks_dir()
    blocks = load_all_blocks(blocks_dir)
    valid_intents = {"build", "debug", "migrate", "review"}
    for block_id, block in blocks.items():
        assert block.slug, f"{block_id}: missing slug"
        assert block.domain, f"{block_id}: missing domain"
        assert block.intent in valid_intents, f"{block_id}: invalid intent '{block.intent}'"
        assert block.constraints or block.anti_patterns, f"{block_id}: no constraints or anti_patterns"
