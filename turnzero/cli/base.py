"""Shared utilities and constants for the TurnZero CLI."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

import typer
from rich.console import Console

from turnzero.config import (
    _blocks_dir,  # noqa: F401
    _bundled_blocks_dir,  # noqa: F401
    _bundled_index_path,  # noqa: F401
    _data_dir,  # noqa: F401
    _index_path,  # noqa: F401
)

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
