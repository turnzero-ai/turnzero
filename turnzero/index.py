"""Backward-compat shim — real implementations live in repositories/index_repo.py."""

from __future__ import annotations

from turnzero.repositories.index_repo import IndexHeader, build, load_index, verify

__all__ = ["IndexHeader", "build", "load_index", "verify"]
