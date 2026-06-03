"""Tests for turnzero/proxy/clients/ — Continue.dev patching and client detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from turnzero.proxy.clients.continue_dev import _ENTRY_TITLE
from turnzero.proxy.clients.continue_dev import patch as patch_continue
from turnzero.proxy.clients.cursor import is_installed as cursor_installed
from turnzero.proxy.clients.windsurf import is_installed as windsurf_installed

_PORT = 9981
_SECRET = "test-secret-xyz"


# ---------------------------------------------------------------------------
# continue_dev.patch
# ---------------------------------------------------------------------------


def test_continue_patches_empty_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"

    with patch("turnzero.proxy.clients.continue_dev._CONFIG_PATH", config_path):
        patch_continue(port=_PORT, secret=_SECRET)

    cfg = json.loads(config_path.read_text())
    models = cfg["models"]
    assert len(models) == 1
    entry = models[0]
    assert entry["title"] == _ENTRY_TITLE
    assert f"localhost:{_PORT}" in entry["apiBase"]
    assert entry["requestOptions"]["headers"]["X-TurnZero-Secret"] == _SECRET


def test_continue_patches_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    existing = {"models": [{"title": "GPT-4", "provider": "openai", "model": "gpt-4"}]}
    config_path.write_text(json.dumps(existing))

    with patch("turnzero.proxy.clients.continue_dev._CONFIG_PATH", config_path):
        patch_continue(port=_PORT, secret=_SECRET)

    cfg = json.loads(config_path.read_text())
    models = cfg["models"]
    assert len(models) == 2
    titles = [m["title"] for m in models]
    assert "GPT-4" in titles
    assert _ENTRY_TITLE in titles


def test_continue_is_idempotent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"

    with patch("turnzero.proxy.clients.continue_dev._CONFIG_PATH", config_path):
        patch_continue(port=_PORT, secret=_SECRET)
        patch_continue(port=_PORT, secret=_SECRET)

    cfg = json.loads(config_path.read_text())
    turnzero_entries = [m for m in cfg["models"] if m["title"] == _ENTRY_TITLE]
    assert len(turnzero_entries) == 1


def test_continue_updates_existing_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    old_entry = {
        "title": _ENTRY_TITLE,
        "provider": "openai",
        "model": "gpt-4o",
        "apiBase": "http://localhost:9000/v1",
        "apiKey": "my-real-key",
        "requestOptions": {"headers": {"X-TurnZero-Secret": "old-secret"}},
    }
    config_path.write_text(json.dumps({"models": [old_entry]}))

    new_secret = "new-secret-456"
    with patch("turnzero.proxy.clients.continue_dev._CONFIG_PATH", config_path):
        patch_continue(port=9982, secret=new_secret)

    cfg = json.loads(config_path.read_text())
    entry = next(m for m in cfg["models"] if m["title"] == _ENTRY_TITLE)
    assert "9982" in entry["apiBase"]
    assert entry["requestOptions"]["headers"]["X-TurnZero-Secret"] == new_secret
    # Existing user API key must be preserved
    assert entry["apiKey"] == "my-real-key"


def test_continue_creates_parent_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.json"

    with patch("turnzero.proxy.clients.continue_dev._CONFIG_PATH", config_path):
        patch_continue(port=_PORT, secret=_SECRET)

    assert config_path.exists()


# ---------------------------------------------------------------------------
# cursor / windsurf detection
# ---------------------------------------------------------------------------


def test_cursor_detects_not_installed(tmp_path: Path) -> None:
    absent = tmp_path / "Cursor"
    with patch("turnzero.proxy.clients.cursor._app_support_path", return_value=absent):
        assert cursor_installed() is False


def test_cursor_detects_installed(tmp_path: Path) -> None:
    present = tmp_path / "Cursor"
    present.mkdir()
    with patch("turnzero.proxy.clients.cursor._app_support_path", return_value=present):
        assert cursor_installed() is True


def test_windsurf_detects_not_installed(tmp_path: Path) -> None:
    absent = tmp_path / "Windsurf"
    with patch("turnzero.proxy.clients.windsurf._app_support_path", return_value=absent):
        assert windsurf_installed() is False


def test_windsurf_detects_installed(tmp_path: Path) -> None:
    present = tmp_path / "Windsurf"
    present.mkdir()
    with patch("turnzero.proxy.clients.windsurf._app_support_path", return_value=present):
        assert windsurf_installed() is True
