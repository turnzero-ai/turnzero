"""Tests for turnzero/proxy/clients/ — Continue.dev patching and client detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from turnzero.proxy.clients.continue_dev import (
    _ENTRY_NAME,
    _ENTRY_TITLE,
)
from turnzero.proxy.clients.continue_dev import (
    patch as patch_continue,
)
from turnzero.proxy.clients.cursor import is_installed as cursor_installed
from turnzero.proxy.clients.windsurf import is_installed as windsurf_installed

_PORT = 9981
_SECRET = "test-secret-xyz"


# ---------------------------------------------------------------------------
# continue_dev — config.yaml (v1.2+)
# ---------------------------------------------------------------------------


def test_continue_patches_empty_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("name: Local\nversion: 1.0.0\nschema: v1\nmodels: []\n")
    json_path = tmp_path / "config.json"

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=_PORT, secret=_SECRET)

    content = yaml_path.read_text()
    assert _ENTRY_NAME in content
    assert f"localhost:{_PORT}" in content
    assert _SECRET in content


def test_continue_yaml_idempotent(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("name: Local\nversion: 1.0.0\nschema: v1\nmodels: []\n")
    json_path = tmp_path / "config.json"

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=_PORT, secret=_SECRET)
        patch_continue(port=_PORT, secret=_SECRET)

    content = yaml_path.read_text()
    assert content.count(f"- name: {_ENTRY_NAME}") == 1


def test_continue_yaml_updates_secret(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("name: Local\nversion: 1.0.0\nschema: v1\nmodels: []\n")
    json_path = tmp_path / "config.json"

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=_PORT, secret="old-secret")
        patch_continue(port=9982, secret="new-secret")

    content = yaml_path.read_text()
    assert "new-secret" in content
    assert "old-secret" not in content
    assert content.count(f"- name: {_ENTRY_NAME}") == 1


# ---------------------------------------------------------------------------
# continue_dev — config.json (legacy)
# ---------------------------------------------------------------------------


def test_continue_patches_empty_json(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"  # absent — skip yaml patch
    json_path = tmp_path / "config.json"

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=_PORT, secret=_SECRET)

    cfg = json.loads(json_path.read_text())
    models = cfg["models"]
    assert len(models) == 1
    assert models[0]["title"] == _ENTRY_TITLE
    assert f"localhost:{_PORT}" in models[0]["apiBase"]
    assert models[0]["requestOptions"]["headers"]["X-TurnZero-Secret"] == _SECRET


def test_continue_json_patches_existing_config(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    json_path = tmp_path / "config.json"
    existing = {"models": [{"title": "GPT-4", "provider": "openai", "model": "gpt-4"}]}
    json_path.write_text(json.dumps(existing))

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=_PORT, secret=_SECRET)

    cfg = json.loads(json_path.read_text())
    titles = [m["title"] for m in cfg["models"]]
    assert "GPT-4" in titles
    assert _ENTRY_TITLE in titles


def test_continue_json_is_idempotent(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    json_path = tmp_path / "config.json"

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=_PORT, secret=_SECRET)
        patch_continue(port=_PORT, secret=_SECRET)

    cfg = json.loads(json_path.read_text())
    assert len([m for m in cfg["models"] if m["title"] == _ENTRY_TITLE]) == 1


def test_continue_json_preserves_api_key(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    json_path = tmp_path / "config.json"
    old = {
        "models": [{
            "title": _ENTRY_TITLE, "provider": "openai", "model": "gpt-4o",
            "apiBase": "http://localhost:9000/v1", "apiKey": "my-real-key",
            "requestOptions": {"headers": {"X-TurnZero-Secret": "old"}},
        }]
    }
    json_path.write_text(json.dumps(old))

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path),
    ):
        patch_continue(port=9982, secret="new-secret")

    entry = next(m for m in json.loads(json_path.read_text())["models"] if m["title"] == _ENTRY_TITLE)
    assert entry["apiKey"] == "my-real-key"
    assert entry["requestOptions"]["headers"]["X-TurnZero-Secret"] == "new-secret"


def test_continue_creates_parent_dir(tmp_path: Path) -> None:
    yaml_path = tmp_path / "nested" / "config.yaml"
    json_path = tmp_path / "nested" / "config.json"

    with (
        patch("turnzero.proxy.clients.continue_dev._CONFIG_YAML", yaml_path),
        patch("turnzero.proxy.clients.continue_dev._CONFIG_JSON", json_path),
        patch("turnzero.proxy.clients.continue_dev._CONTINUE_DIR", tmp_path / "nested"),
    ):
        patch_continue(port=_PORT, secret=_SECRET)

    assert json_path.exists()


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
