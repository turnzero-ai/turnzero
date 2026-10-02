"""Tests for multi-client setup automation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


# ── ONB-1: starter personal prior template ───────────────────────────────────


def _locate_template() -> Path:
    """Return path to turnzero-guide.yaml regardless of install context."""
    pkg = (
        Path(__file__).parent.parent
        / "data"
        / "templates"
        / "personal"
        / "turnzero-guide.yaml"
    )
    repo = (
        Path(__file__).parent.parent
        / "data"
        / "templates"
        / "personal"
        / "turnzero-guide.yaml"
    )
    return pkg if pkg.exists() else repo


def test_template_copied_when_personal_dir_empty(tmp_path: Path) -> None:
    personal_dir = tmp_path / "personal"
    personal_dir.mkdir()
    template_src = _locate_template()
    assert template_src.exists(), (
        "turnzero-guide.yaml template missing from data/templates"
    )

    dst = personal_dir / "turnzero-guide.yaml"
    if not dst.exists():
        shutil.copy2(template_src, dst)

    assert dst.exists()
    content = dst.read_text()
    assert "turnzero-guide" in content
    assert "full_text" in content
    assert "submit_candidate" in content


def test_template_not_overwritten_when_personal_dir_has_files(tmp_path: Path) -> None:
    personal_dir = tmp_path / "personal"
    personal_dir.mkdir()
    existing = personal_dir / "my-prior.yaml"
    existing.write_text("slug: my-prior\n")

    existing_yamls = list(personal_dir.glob("*.yaml"))
    assert len(existing_yamls) == 1

    template_dst = personal_dir / "turnzero-guide.yaml"
    if not existing_yamls:
        shutil.copy2(_locate_template(), template_dst)

    assert not template_dst.exists()
    assert existing.exists()


# ── RET-1: live injection demo ────────────────────────────────────────────────


def test_live_demo_shows_results_when_blocks_returned() -> None:
    """_render_demo_results prints block slugs and token totals when retrieval succeeds."""
    fake_results = [
        {
            "block_id": "personal-prior-1",
            "score": 2.0,
            "context_weight": 200,
            "domain": "global",
            "preview": "Keep answers short",
        },
        {
            "block_id": "fastapi-async-build",
            "score": 0.9,
            "context_weight": 800,
            "domain": "fastapi",
            "preview": "Use async def for all endpoint…",
        },
    ]

    with patch("turnzero.mcp_server._list_suggested_blocks", return_value=fake_results):
        con = MagicMock()
        with patch("turnzero.cli.setup.console", con):
            from turnzero.cli.setup import _render_demo_results

            _render_demo_results("test prompt")

    printed = " ".join(str(c) for c in con.print.call_args_list)
    assert "fastapi-async-build" in printed
    assert "800" in printed
    assert "1 personal" in printed
    assert "1 expert" in printed


def test_live_demo_graceful_on_empty_results() -> None:
    """_render_demo_results prints a warning when no blocks match."""
    with patch("turnzero.mcp_server._list_suggested_blocks", return_value=[]):
        con = MagicMock()
        with patch("turnzero.cli.setup.console", con):
            from turnzero.cli.setup import _render_demo_results

            _render_demo_results("test prompt")

    printed = " ".join(str(c) for c in con.print.call_args_list)
    assert "No blocks matched" in printed


def test_live_demo_graceful_on_exception() -> None:
    """_render_demo_results catches retrieval errors and prints a fallback."""
    with patch(
        "turnzero.mcp_server._list_suggested_blocks",
        side_effect=RuntimeError("embedding unavailable"),
    ):
        con = MagicMock()
        with patch("turnzero.cli.setup.console", con):
            from turnzero.cli.setup import _render_demo_results

            _render_demo_results("test prompt")

    printed = " ".join(str(c) for c in con.print.call_args_list)
    assert "Live demo skipped" in printed


def test_template_yaml_is_valid_block_schema(tmp_path: Path) -> None:
    import yaml

    template_src = _locate_template()
    assert template_src.exists()
    data = yaml.safe_load(template_src.read_text())

    assert data["slug"] == "turnzero-guide"
    assert data["domain"] == "global"
    assert data["tier"] == "personal"
    assert isinstance(data["constraints"], list) and len(data["constraints"]) > 0
    assert isinstance(data["anti_patterns"], list) and len(data["anti_patterns"]) > 0
    assert all(ap.startswith("Do not") for ap in data["anti_patterns"])


def test_client_instructions_do_not_require_inject_block() -> None:
    from turnzero.cli import setup as setup_mod

    assert "Use `inject_block`" not in setup_mod._TURNZERO_MD_BLOCK
    assert "full text" in setup_mod._TURNZERO_MD_BLOCK


def test_starter_prior_does_not_require_inject_block() -> None:
    import yaml

    template = (
        Path(__file__).parent.parent
        / "data"
        / "templates"
        / "personal"
        / "turnzero-guide.yaml"
    )
    data = yaml.safe_load(template.read_text(encoding="utf-8"))

    assert not any("call inject_block for every" in c for c in data["constraints"])
    assert not any("always call inject_block" in a for a in data["anti_patterns"])
    assert all(a.startswith("Do not") for a in data["anti_patterns"])


def test_setup_demo_counts_personal_priors_as_personal(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from turnzero.cli import setup as setup_mod

    prior = data_dir / "blocks" / "personal" / "global" / "style.yaml"
    prior.parent.mkdir(parents=True)
    prior.write_text(
        "slug: style\nversion: 1.0.0\ndomain: global\nintent: build\n"
        "last_verified: 2026-05-01\ncontext_weight: 100\n"
        'constraints:\n  - "Keep answers short"\nanti_patterns: []\n'
        "confidence: 0.9\narchived: false\n",
        encoding="utf-8",
    )

    setup_mod._render_demo_results("hi")

    out = capsys.readouterr().out
    assert "Personal Priors" in out
    assert "1 rule" in out
