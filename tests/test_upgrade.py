"""Tests for upgrade check — caching, version comparison, failure handling."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from turnzero.upgrade import _is_newer, check_for_upgrade


def test_is_newer_detects_higher_version() -> None:
    assert _is_newer("0.11.0", "0.10.1") is True


def test_is_newer_same_version() -> None:
    assert _is_newer("0.10.1", "0.10.1") is False


def test_is_newer_older_version() -> None:
    assert _is_newer("0.9.0", "0.10.1") is False


def test_is_newer_malformed_returns_false() -> None:
    assert _is_newer("not-a-version", "0.10.1") is False


def test_check_fetches_pypi_and_caches(tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"info": {"version": "99.0.0"}}
    mock_resp.raise_for_status = MagicMock()

    with (
        patch("turnzero.upgrade._installed_version", return_value="0.10.1"),
        patch("httpx.get", return_value=mock_resp) as mock_get,
    ):
        latest, is_newer = check_for_upgrade(tmp_path)

    assert latest == "99.0.0"
    assert is_newer is True
    mock_get.assert_called_once()

    cache = json.loads((tmp_path / "upgrade_check.json").read_text())
    assert cache["latest"] == "99.0.0"


def test_check_uses_cache_within_24h(tmp_path: Path) -> None:
    cache_path = tmp_path / "upgrade_check.json"
    cache_path.write_text(
        json.dumps({"latest": "99.0.0", "checked_at": time.time()}),
        encoding="utf-8",
    )

    with (
        patch("turnzero.upgrade._installed_version", return_value="0.10.1"),
        patch("httpx.get") as mock_get,
    ):
        latest, is_newer = check_for_upgrade(tmp_path)

    assert latest == "99.0.0"
    assert is_newer is True
    mock_get.assert_not_called()


def test_check_refetches_after_cache_expires(tmp_path: Path) -> None:
    cache_path = tmp_path / "upgrade_check.json"
    cache_path.write_text(
        json.dumps({"latest": "0.10.0", "checked_at": 0.0}),
        encoding="utf-8",
    )
    # Set mtime to 25h ago so cache is stale
    stale_mtime = time.time() - 90_000
    import os
    os.utime(cache_path, (stale_mtime, stale_mtime))

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"info": {"version": "99.1.0"}}
    mock_resp.raise_for_status = MagicMock()

    with (
        patch("turnzero.upgrade._installed_version", return_value="0.10.1"),
        patch("httpx.get", return_value=mock_resp),
    ):
        latest, is_newer = check_for_upgrade(tmp_path)

    assert latest == "99.1.0"


def test_check_silent_on_network_error(tmp_path: Path) -> None:
    with (
        patch("turnzero.upgrade._installed_version", return_value="0.10.1"),
        patch("httpx.get", side_effect=Exception("network down")),
    ):
        latest, is_newer = check_for_upgrade(tmp_path)

    assert latest is None
    assert is_newer is False


def test_check_silent_on_unknown_version(tmp_path: Path) -> None:
    with patch("turnzero.upgrade._installed_version", return_value="unknown"):
        latest, is_newer = check_for_upgrade(tmp_path)

    assert latest is None
    assert is_newer is False
