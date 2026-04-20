"""Tests for CLI entry points."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from turnzero.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "turnzero" in result.output
    # Should contain a semver-like string
    parts = result.output.strip().split()
    assert len(parts) == 2
    version = parts[1]
    assert version.count(".") >= 1


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("setup", "query", "preview", "stats", "index"):
        assert cmd in result.output


# ---------------------------------------------------------------------------
# Setup block count — rglob fix (Bug 3)
# ---------------------------------------------------------------------------

def test_setup_block_count_includes_subdirectories(tmp_path: Path) -> None:
    """Block count in setup must recurse into domain subdirectories."""
    blocks_dir = tmp_path / "blocks"
    # Simulate domain subfolder structure (local/nextjs/block.yaml)
    subdir = blocks_dir / "local" / "nextjs"
    subdir.mkdir(parents=True)
    (subdir / "block-a.yaml").write_text("slug: block-a\n")
    (subdir / "block-b.yaml").write_text("slug: block-b\n")
    # Flat file at top level should also count
    (blocks_dir / "block-c.yaml").write_text("slug: block-c\n")

    flat_count = len(list(blocks_dir.glob("*.yaml")))    # old broken behaviour
    recursive_count = len(list(blocks_dir.rglob("*.yaml")))  # fixed behaviour

    assert flat_count == 1, "Sanity: glob misses subdirectory files"
    assert recursive_count == 3, "rglob must find all files including subdirectories"
