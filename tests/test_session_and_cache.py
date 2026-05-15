"""Tests for SessionLifecycle (REF-1) and CachedLoader (REF-6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from turnzero.cache import CachedLoader
from turnzero.session import SessionLifecycle


def test_session_lifecycle_exposes_all_operations(tmp_path: Path) -> None:
    """SessionLifecycle provides the full session state API without direct state.py imports."""
    data_dir = tmp_path / "turnzero"

    with patch("turnzero.config.get_data_dir", return_value=data_dir):
        session_id = "lifecycle-test"
        block_id = "fastapi-async-build"
        project_root = tmp_path / "project"
        project_root.mkdir()

        # record + get
        SessionLifecycle.record_session_injection(session_id, block_id)
        injections = SessionLifecycle.get_session_injections(session_id)
        assert block_id in injections

        # clear
        SessionLifecycle.clear_session_injections(session_id)
        assert not SessionLifecycle.get_session_injections(session_id)

        # affinity
        SessionLifecycle.record_project_affinity(project_root, block_id)
        affinity = SessionLifecycle.get_project_affinity(project_root)
        assert affinity.get(block_id) == 1

        # project hash is stable
        h1 = SessionLifecycle.get_project_hash(project_root)
        h2 = SessionLifecycle.get_project_hash(project_root)
        assert h1 == h2
        assert len(h1) == 16


def test_cached_loader_caches_on_stable_mtime(tmp_path: Path) -> None:
    """CachedLoader returns cached value when mtime is unchanged."""
    call_count = 0

    def loader() -> list[str]:
        nonlocal call_count
        call_count += 1
        return ["block-a"]

    mtime_val = 1000.0

    cache: CachedLoader[list[str]] = CachedLoader(
        loader_fn=loader,
        get_mtime_fn=lambda: mtime_val,
    )

    first = cache.get()
    second = cache.get()

    assert first == ["block-a"]
    assert first is second  # same object — no reload
    assert call_count == 1


def test_cached_loader_reloads_on_mtime_change(tmp_path: Path) -> None:
    """CachedLoader reloads when mtime changes."""
    call_count = 0
    mtime_val = 1000.0

    def loader() -> list[str]:
        nonlocal call_count
        call_count += 1
        return [f"block-{call_count}"]

    cache: CachedLoader[list[str]] = CachedLoader(
        loader_fn=loader,
        get_mtime_fn=lambda: mtime_val,
    )

    first = cache.get()
    assert first == ["block-1"]

    mtime_val = 2000.0
    second = cache.get()
    assert second == ["block-2"]
    assert call_count == 2


def test_cached_loader_invalidate_forces_reload() -> None:
    """CachedLoader.invalidate() forces reload on next get()."""
    call_count = 0

    def loader() -> int:
        nonlocal call_count
        call_count += 1
        return call_count

    cache: CachedLoader[int] = CachedLoader(loader_fn=loader, get_mtime_fn=lambda: 1.0)
    assert cache.get() == 1
    assert cache.get() == 1  # cached

    cache.invalidate()
    assert cache.get() == 2  # reloaded
