"""Shared utilities and constants for the TurnZero CLI."""

from __future__ import annotations

import os
from importlib.metadata import version as _pkg_version
from pathlib import Path

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"turnzero {_pkg_version('turnzero')}")
        raise typer.Exit()

DEFAULT_THRESHOLD = 0.70
MIN_HARVEST_WORDS = 100
STALENESS_THRESHOLD = 0.70
MAX_PREVIEW_CONSTRAINTS = 3
MAX_PREVIEW_ANTI_PATTERNS = 2
PREVIEW_TEXT_LIMIT = 90
HTTP_OK = 200
LOW_CONFIDENCE_THRESHOLD = 0.70
THRESHOLD_TEST_GOOD_RECALL = 0.80
THRESHOLD_TEST_WARN_RECALL = 0.60


def _data_dir() -> Path:
    if env := os.environ.get("TURNZERO_DATA_DIR"):
        return Path(env)
    user_dir = Path.home() / ".turnzero"
    if user_dir.exists():
        return user_dir
    return Path("data")


def _blocks_dir() -> Path:
    return _data_dir() / "blocks"


def _bundled_index_path() -> Path:
    """Return the pre-built index shipped inside the package (no setup needed)."""
    # Path(__file__) is turnzero/cli/base.py
    # .parent is turnzero/cli/
    # .parent.parent is turnzero/
    pkg = Path(__file__).parent.parent / "data" / "index.jsonl"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent.parent / "data" / "index.jsonl"
    if repo.exists():
        return repo
    return _index_path()


def _bundled_blocks_dir() -> Path:
    """Return the blocks directory shipped inside the package (no setup needed)."""
    pkg = Path(__file__).parent.parent / "data" / "blocks"
    if pkg.exists():
        return pkg
    repo = Path(__file__).parent.parent.parent / "data" / "blocks"
    if repo.exists():
        return repo
    return _blocks_dir()


def _index_path() -> Path:
    return _data_dir() / "index.jsonl"
