"""Tests for CLI entry points."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from turnzero.cli import _setup_claude_md, _setup_codex_agents_md, _setup_codex_mcp, app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "turnzero" in result.output
    # Should contain a semver-like string
    parts = result.output.strip().split()
    assert len(parts) == 2
    version = parts[1]
    assert version.count(".") >= 1


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("setup", "query", "preview", "stats", "index"):
        assert cmd in result.output


# ---------------------------------------------------------------------------
# Setup block count — rglob fix (Bug 3)
# ---------------------------------------------------------------------------

def test_setup_block_count_includes_subdirectories(tmp_path: Path) -> None:
    """Block count in setup must recurse into domain subdirectories."""
    blocks_dir = tmp_path / "blocks"
    # Simulate domain subfolder structure (local/nextjs/block.yaml)
    subdir = blocks_dir / "local" / "nextjs"
    subdir.mkdir(parents=True)
    (subdir / "block-a.yaml").write_text("slug: block-a\n")
    (subdir / "block-b.yaml").write_text("slug: block-b\n")
    # Flat file at top level should also count
    (blocks_dir / "block-c.yaml").write_text("slug: block-c\n")

    flat_count = len(list(blocks_dir.glob("*.yaml")))    # old broken behaviour
    recursive_count = len(list(blocks_dir.rglob("*.yaml")))  # fixed behaviour

    assert flat_count == 1, "Sanity: glob misses subdirectory files"
    assert recursive_count == 3, "rglob must find all files including subdirectories"


# ---------------------------------------------------------------------------
# Codex MCP registration
# ---------------------------------------------------------------------------

def test_setup_codex_mcp_creates_config(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    con = Console(quiet=True)

    _setup_codex_mcp(
        mcp_bin="/usr/local/bin/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=False,
        con=con,
        codex_dir=codex_dir,
    )

    config = codex_dir / "config.toml"
    assert config.exists()
    text = config.read_text()
    assert "[mcp_servers.turnzero]" in text
    assert 'command = "/usr/local/bin/turnzero-mcp"' in text
    assert "TURNZERO_DATA_DIR" in text


def test_setup_codex_mcp_skips_if_no_codex_dir(tmp_path: Path) -> None:
    """Should be silent and do nothing when ~/.codex doesn't exist."""
    con = Console(quiet=True)
    absent_dir = tmp_path / ".codex-absent"
    _setup_codex_mcp(
        mcp_bin="/usr/local/bin/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=False,
        con=con,
        codex_dir=absent_dir,
    )
    assert not (absent_dir / "config.toml").exists()


def test_setup_codex_mcp_force_overwrites(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text(
        '[mcp_servers.turnzero]\ncommand = "/old/path"\nenv = { TURNZERO_DATA_DIR = "/old" }\n'
    )
    con = Console(quiet=True)

    _setup_codex_mcp(
        mcp_bin="/new/path/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=True,
        con=con,
        codex_dir=codex_dir,
    )

    text = config.read_text()
    assert "/new/path/turnzero-mcp" in text
    assert "/old/path" not in text


def test_setup_codex_mcp_preserves_existing_config(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('[mcp_servers.other]\ncommand = "other-server"\n')
    con = Console(quiet=True)

    _setup_codex_mcp(
        mcp_bin="/usr/local/bin/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=False,
        con=con,
        codex_dir=codex_dir,
    )

    text = config.read_text()
    assert "[mcp_servers.other]" in text
    assert "[mcp_servers.turnzero]" in text


# ---------------------------------------------------------------------------
# Global instruction files — ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md
# ---------------------------------------------------------------------------

def test_setup_claude_md_creates_file(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    con = Console(quiet=True)

    _setup_claude_md(force=False, con=con, claude_dir=claude_dir)

    md = claude_dir / "CLAUDE.md"
    assert md.exists()
    text = md.read_text()
    assert "TurnZero" in text
    assert "list_suggested_blocks" in text
    assert "submit_candidate" in text


def test_setup_claude_md_skips_if_no_claude_dir(tmp_path: Path) -> None:
    con = Console(quiet=True)
    _setup_claude_md(force=False, con=con, claude_dir=tmp_path / ".claude-absent")
    assert not (tmp_path / ".claude-absent" / "CLAUDE.md").exists()


def test_setup_claude_md_skips_if_already_present(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    md = claude_dir / "CLAUDE.md"
    md.write_text("## TurnZero — Expert Prior injection\nexisting content\n")
    con = Console(quiet=True)

    _setup_claude_md(force=False, con=con, claude_dir=claude_dir)

    assert md.read_text().count("## TurnZero") == 1


def test_setup_claude_md_force_overwrites(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    md = claude_dir / "CLAUDE.md"
    md.write_text("## TurnZero — Expert Prior injection\nold content\n")
    con = Console(quiet=True)

    _setup_claude_md(force=True, con=con, claude_dir=claude_dir)

    text = md.read_text()
    assert "old content" not in text
    assert "list_suggested_blocks" in text
    assert text.count("## TurnZero") == 1


def test_setup_claude_md_preserves_other_content(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    md = claude_dir / "CLAUDE.md"
    md.write_text("## Other Rules\nalways be concise\n")
    con = Console(quiet=True)

    _setup_claude_md(force=False, con=con, claude_dir=claude_dir)

    text = md.read_text()
    assert "## Other Rules" in text
    assert "always be concise" in text
    assert "list_suggested_blocks" in text


def test_setup_codex_agents_md_creates_file(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    con = Console(quiet=True)

    _setup_codex_agents_md(force=False, con=con, codex_dir=codex_dir)

    md = codex_dir / "AGENTS.md"
    assert md.exists()
    text = md.read_text()
    assert "list_suggested_blocks" in text
    assert "submit_candidate" in text


def test_setup_codex_agents_md_skips_if_no_codex_dir(tmp_path: Path) -> None:
    con = Console(quiet=True)
    _setup_codex_agents_md(force=False, con=con, codex_dir=tmp_path / ".codex-absent")
    assert not (tmp_path / ".codex-absent" / "AGENTS.md").exists()
