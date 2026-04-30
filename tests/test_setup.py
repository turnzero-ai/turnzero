"""Tests for multi-client setup automation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from turnzero.cli.setup import (
    _setup_claude_desktop_mcp,
    _setup_cursor_mcp,
    _setup_gemini_mcp,
    _setup_gemini_md,
)


def test_setup_claude_desktop_mcp_macos(tmp_path: Path):
    home = tmp_path / "home"
    config_dir = home / "Library/Application Support/Claude"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "claude_desktop_config.json"

    mcp_bin = "/usr/local/bin/turnzero-mcp"
    data_dir = home / ".turnzero"
    con = MagicMock()

    with (
        patch("pathlib.Path.home", return_value=home),
        patch("platform.system", return_value="Darwin"),
    ):
        _setup_claude_desktop_mcp(mcp_bin, data_dir, force=False, con=con)

    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["turnzero"]["command"] == mcp_bin
    assert data["mcpServers"]["turnzero"]["env"]["TURNZERO_DATA_DIR"] == str(data_dir)


def test_setup_cursor_mcp_macos(tmp_path: Path):
    home = tmp_path / "home"
    config_dir = (
        home
        / "Library/Application Support/Cursor/User/globalStorage/saoudrizwan.claude-dev/settings"
    )
    config_dir.mkdir(parents=True)
    config_file = config_dir / "mcp_servers.json"

    mcp_bin = "/usr/local/bin/turnzero-mcp"
    data_dir = home / ".turnzero"
    con = MagicMock()

    with (
        patch("pathlib.Path.home", return_value=home),
        patch("platform.system", return_value="Darwin"),
    ):
        _setup_cursor_mcp(mcp_bin, data_dir, force=False, con=con)

    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["turnzero"]["command"] == mcp_bin
    assert data["mcpServers"]["turnzero"]["env"]["TURNZERO_DATA_DIR"] == str(data_dir)


def test_setup_skips_if_not_installed(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    # No config dirs created

    mcp_bin = "/usr/local/bin/turnzero-mcp"
    data_dir = home / ".turnzero"
    con = MagicMock()

    with (
        patch("pathlib.Path.home", return_value=home),
        patch("platform.system", return_value="Darwin"),
    ):
        _setup_claude_desktop_mcp(mcp_bin, data_dir, force=False, con=con)
        _setup_cursor_mcp(mcp_bin, data_dir, force=False, con=con)

    # Should not create directories or files if not already present
    assert not (home / "Library").exists()


def test_setup_gemini_mcp(tmp_path: Path):
    home = tmp_path / "home"
    config_dir = home / ".gemini"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "settings.json"

    mcp_bin = "/usr/local/bin/turnzero-mcp"
    data_dir = home / ".turnzero"
    con = MagicMock()

    with patch("pathlib.Path.home", return_value=home):
        _setup_gemini_mcp(mcp_bin, data_dir, force=False, con=con)

    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["turnzero"]["command"] == mcp_bin
    assert data["mcpServers"]["turnzero"]["env"]["TURNZERO_DATA_DIR"] == str(data_dir)


def test_setup_gemini_md(tmp_path: Path):
    home = tmp_path / "home"
    config_dir = home / ".gemini"
    config_dir.mkdir(parents=True)
    md_file = config_dir / "GEMINI.md"

    con = MagicMock()

    with patch("pathlib.Path.home", return_value=home):
        _setup_gemini_md(force=False, con=con)

    assert md_file.exists()
    content = md_file.read_text()
    assert "## TurnZero — Expert & Personal Prior Injection" in content
