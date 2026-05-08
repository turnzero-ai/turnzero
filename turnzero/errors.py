"""TurnZero exception hierarchy.

All user-facing errors subclass TurnZeroError. cli_entry() catches them and
formats them cleanly — no scattered err_console.print() + typer.Exit(1) patterns.
"""

from __future__ import annotations


class TurnZeroError(Exception):
    """Base class for all user-facing TurnZero errors."""
    exit_code: int = 1


class SetupRequired(TurnZeroError):
    """No index or blocks found — user needs to run turnzero setup."""


class BackendNotReady(TurnZeroError):
    """No embedding backend is available."""


class BlockNotFound(TurnZeroError):
    """Requested block ID does not exist in the library."""


class ConfigError(TurnZeroError):
    """Malformed or missing configuration."""
