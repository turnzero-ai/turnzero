"""Client auto-setup helpers for proxy-aware IDEs."""

from __future__ import annotations

from turnzero.proxy.clients.continue_dev import is_installed as continue_installed
from turnzero.proxy.clients.continue_dev import patch as patch_continue
from turnzero.proxy.clients.cursor import is_installed as cursor_installed
from turnzero.proxy.clients.cursor import print_instructions as cursor_instructions
from turnzero.proxy.clients.windsurf import is_installed as windsurf_installed
from turnzero.proxy.clients.windsurf import print_instructions as windsurf_instructions

__all__ = [
    "patch_continue",
    "continue_installed",
    "cursor_installed",
    "cursor_instructions",
    "windsurf_installed",
    "windsurf_instructions",
]
