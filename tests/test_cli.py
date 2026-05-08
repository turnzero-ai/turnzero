"""Tests for CLI entry points."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from turnzero.cli import app
from turnzero.cli.setup import (
    _setup_claude_md,
    _setup_codex_agents_md,
    _setup_codex_mcp,
)

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

    flat_count = len(list(blocks_dir.glob("*.yaml")))  # old broken behaviour
    recursive_count = len(list(blocks_dir.rglob("*.yaml")))  # fixed behaviour

    assert flat_count == 1, "Sanity: glob misses subdirectory files"
    assert recursive_count == 3, "rglob must find all files including subdirectories"


# ---------------------------------------------------------------------------
# Codex MCP registration
# ---------------------------------------------------------------------------


def test_setup_codex_mcp_creates_config(tmp_path: Path, quiet_console: Console) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    _setup_codex_mcp(
        mcp_bin="/usr/local/bin/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=False,
        con=quiet_console,
        codex_dir=codex_dir,
    )

    config = codex_dir / "config.toml"
    assert config.exists()
    text = config.read_text()
    assert "[mcp_servers.turnzero]" in text
    assert 'command = "/usr/local/bin/turnzero-mcp"' in text
    assert "TURNZERO_DATA_DIR" in text


def test_setup_codex_mcp_skips_if_no_codex_dir(tmp_path: Path, quiet_console: Console) -> None:
    """Should be silent and do nothing when ~/.codex doesn't exist."""
    absent_dir = tmp_path / ".codex-absent"
    _setup_codex_mcp(
        mcp_bin="/usr/local/bin/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=False,
        con=quiet_console,
        codex_dir=absent_dir,
    )
    assert not (absent_dir / "config.toml").exists()


def test_setup_codex_mcp_force_overwrites(tmp_path: Path, quiet_console: Console) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text(
        '[mcp_servers.turnzero]\ncommand = "/old/path"\nenv = { TURNZERO_DATA_DIR = "/old" }\n'
    )

    _setup_codex_mcp(
        mcp_bin="/new/path/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=True,
        con=quiet_console,
        codex_dir=codex_dir,
    )

    text = config.read_text()
    assert "/new/path/turnzero-mcp" in text
    assert "/old/path" not in text


def test_setup_codex_mcp_preserves_existing_config(tmp_path: Path, quiet_console: Console) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('[mcp_servers.other]\ncommand = "other-server"\n')

    _setup_codex_mcp(
        mcp_bin="/usr/local/bin/turnzero-mcp",
        data_dir=tmp_path / ".turnzero",
        force=False,
        con=quiet_console,
        codex_dir=codex_dir,
    )

    text = config.read_text()
    assert "[mcp_servers.other]" in text
    assert "[mcp_servers.turnzero]" in text


# ---------------------------------------------------------------------------
# Global instruction files — ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md
# ---------------------------------------------------------------------------


def test_setup_claude_md_creates_file(tmp_path: Path, quiet_console: Console) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    _setup_claude_md(force=False, con=quiet_console, claude_dir=claude_dir)

    md = claude_dir / "CLAUDE.md"
    assert md.exists()
    text = md.read_text()
    assert "TurnZero" in text
    assert "list_suggested_blocks" in text
    assert "submit_candidate" in text


def test_setup_claude_md_skips_if_no_claude_dir(tmp_path: Path, quiet_console: Console) -> None:
    _setup_claude_md(force=False, con=quiet_console, claude_dir=tmp_path / ".claude-absent")
    assert not (tmp_path / ".claude-absent" / "CLAUDE.md").exists()


def test_setup_claude_md_skips_if_already_present(tmp_path: Path, quiet_console: Console) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    md = claude_dir / "CLAUDE.md"
    md.write_text("## TurnZero — Expert & Personal Prior Injection\nexisting content\n")

    _setup_claude_md(force=False, con=quiet_console, claude_dir=claude_dir)

    assert md.read_text().count("## TurnZero") == 1


def test_setup_claude_md_force_overwrites(tmp_path: Path, quiet_console: Console) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    md = claude_dir / "CLAUDE.md"
    md.write_text("## TurnZero — Expert & Personal Prior Injection\nold content\n")

    _setup_claude_md(force=True, con=quiet_console, claude_dir=claude_dir)

    text = md.read_text()
    assert "old content" not in text
    assert "list_suggested_blocks" in text
    assert text.count("## TurnZero") == 1


def test_setup_claude_md_preserves_other_content(tmp_path: Path, quiet_console: Console) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    md = claude_dir / "CLAUDE.md"
    md.write_text("## Other Rules\nalways be concise\n")

    _setup_claude_md(force=False, con=quiet_console, claude_dir=claude_dir)

    text = md.read_text()
    assert "## Other Rules" in text
    assert "always be concise" in text
    assert "list_suggested_blocks" in text


def test_setup_codex_agents_md_creates_file(tmp_path: Path, quiet_console: Console) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    _setup_codex_agents_md(force=False, con=quiet_console, codex_dir=codex_dir)

    md = codex_dir / "AGENTS.md"
    assert md.exists()
    text = md.read_text()
    assert "list_suggested_blocks" in text
    assert "submit_candidate" in text


def test_setup_codex_agents_md_skips_if_no_codex_dir(tmp_path: Path, quiet_console: Console) -> None:
    _setup_codex_agents_md(force=False, con=quiet_console, codex_dir=tmp_path / ".codex-absent")
    assert not (tmp_path / ".codex-absent" / "AGENTS.md").exists()


# ---------------------------------------------------------------------------
# query --explain (RET-4)
# ---------------------------------------------------------------------------


def test_query_explain_chitchat_fails_gate(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chitchat prompt must show impl gate failure, not inject blocks."""
    result = runner.invoke(app, ["query", "thanks that looks great", "--explain"])
    assert result.exit_code == 0
    assert "Explain" in result.output
    assert "✗ failed" in result.output
    assert "No blocks inject" in result.output
    assert "Matched" not in result.output


def test_query_explain_impl_prompt_passes_gate(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Technical prompt must show gate passed and intent/domain detection."""
    result = runner.invoke(app, ["query", "build a fastapi endpoint", "--explain"])
    assert result.exit_code == 0
    assert "Explain" in result.output
    assert "✓ passed" in result.output
    assert "Intent detected" in result.output
    assert "Domain detected" in result.output
    assert "Threshold" in result.output


def test_query_explain_shows_outcome_section(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explain output shows either matched blocks or 'No Expert Priors' message."""
    result = runner.invoke(app, ["query", "build a fastapi endpoint", "--explain"])
    assert result.exit_code == 0
    has_matched = "Matched" in result.output
    has_no_match = "No Expert Priors above threshold" in result.output
    assert has_matched or has_no_match


def test_query_no_match_hints_explain(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no blocks match without --explain, output hints to use --explain."""
    # Nonsense prompt has zero lexical overlap with any block → all scores below threshold.
    # Empty data dir → no personal priors. Combined: results is empty.
    result = runner.invoke(app, ["query", "xyzzy qwerty plonk frobnicate"])
    assert result.exit_code == 0
    assert "--explain" in result.output


# ---------------------------------------------------------------------------
# GRW-1: turnzero list
# ---------------------------------------------------------------------------


def _write_test_block(path: Path, slug: str, domain: str, stale: bool = False) -> None:
    verified = "2020-01-01" if stale else "2026-05-01"
    path.write_text(
        f"slug: {slug}\nversion: 1.0.0\ndomain: {domain}\nintent: build\n"
        f"last_verified: {verified}\ncontext_weight: 100\nconstraints: []\n"
        f"anti_patterns: []\nconfidence: 0.9\narchived: false\n"
    )


def test_list_domain_summary(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks_dir = data_dir / "blocks" / "community" / "fastapi"
    blocks_dir.mkdir(parents=True)
    _write_test_block(blocks_dir / "fastapi-async-build.yaml", "fastapi-async-build", "fastapi")
    _write_test_block(blocks_dir / "fastapi-cors-build.yaml", "fastapi-cors-build", "fastapi")
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_blocks_dir", lambda: data_dir / "blocks")

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "fastapi" in result.output
    assert "2" in result.output  # block count


def test_list_domain_filter(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks_dir = data_dir / "blocks" / "community" / "fastapi"
    blocks_dir.mkdir(parents=True)
    _write_test_block(blocks_dir / "fastapi-async-build.yaml", "fastapi-async-build", "fastapi")
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_blocks_dir", lambda: data_dir / "blocks")

    result = runner.invoke(app, ["list", "--domain", "fastapi"])
    assert result.exit_code == 0
    assert "fastapi-async-build" in result.output
    assert "0.90" in result.output


def test_list_candidates_empty(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_data_dir", lambda: data_dir)

    result = runner.invoke(app, ["list", "--candidates"])
    assert result.exit_code == 0
    assert "No candidates" in result.output


def test_list_candidates_shows_pending(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cand_dir = data_dir / "candidates"
    cand_dir.mkdir()
    _write_test_block(cand_dir / "my-rule-build.yaml", "my-rule-build", "fastapi")
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_data_dir", lambda: data_dir)

    result = runner.invoke(app, ["list", "--candidates"])
    assert result.exit_code == 0
    assert "my-rule-build" in result.output


def test_list_stale_none(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks_dir = data_dir / "blocks" / "community" / "fastapi"
    blocks_dir.mkdir(parents=True)
    _write_test_block(blocks_dir / "fresh.yaml", "fresh", "fastapi", stale=False)
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_blocks_dir", lambda: data_dir / "blocks")

    result = runner.invoke(app, ["list", "--stale"])
    assert result.exit_code == 0
    assert "No stale" in result.output


def test_list_stale_shows_old_blocks(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks_dir = data_dir / "blocks" / "community" / "fastapi"
    blocks_dir.mkdir(parents=True)
    _write_test_block(blocks_dir / "old.yaml", "old-block-build", "fastapi", stale=True)
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_blocks_dir", lambda: data_dir / "blocks")

    result = runner.invoke(app, ["list", "--stale"])
    assert result.exit_code == 0
    assert "old-block-build" in result.output


# ---------------------------------------------------------------------------
# RET-6: stats trajectory
# ---------------------------------------------------------------------------


def _write_tool_log(data_dir: Path, entries: list[dict]) -> None:
    import json
    import time

    log = data_dir / "tool_call_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with open(log, "w") as f:
        for e in entries:
            e.setdefault("ts", now)
            f.write(json.dumps(e) + "\n")


def _write_hook_log(data_dir: Path, n_sessions: int) -> None:
    import json
    import time

    log = data_dir / "hook_log.jsonl"
    now = time.time()
    with open(log, "w") as f:
        for _ in range(n_sessions):
            f.write(json.dumps({"ts": now, "blocks": ["b1"], "domains": ["python"]}) + "\n")


def test_stats_shows_7day_trajectory(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_hook_log(data_dir, 3)
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Last 7 days" in result.output
    assert "sessions" in result.output
    assert "injections" in result.output
    assert "corrections" in result.output


def test_stats_corrections_row_no_sessions(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Corrections captured" in result.output
    assert "none yet" in result.output


def test_stats_corrections_counted_from_tool_log(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_hook_log(data_dir, 2)
    _write_tool_log(data_dir, [
        {"tool": "submit_candidate", "meta": {"auto_approve": False}, "tokens_in": 10, "tokens_out": 5},
        {"tool": "submit_candidate", "meta": {"auto_approve": False}, "tokens_in": 10, "tokens_out": 5},
        {"tool": "submit_candidate", "meta": {"auto_approve": True}, "tokens_in": 10, "tokens_out": 5},
    ])
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    # 2 corrections (auto_approve=False), not 3
    assert "2  " in result.output or "+2" in result.output


def test_stats_personal_prior_growth(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks_dir = data_dir / "blocks" / "personal" / "global"
    blocks_dir.mkdir(parents=True)
    _write_test_block(blocks_dir / "my-pref.yaml", "my-pref-build", "global")
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_blocks_dir", lambda: data_dir / "blocks")

    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Personal Priors" in result.output
    # Growth trajectory present (0 → N in Xw)
    assert "0 →" in result.output


# ---------------------------------------------------------------------------
# RET-7: setup finale interactive demo
# ---------------------------------------------------------------------------


def test_finale_non_interactive_uses_demo_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """--no-interactive skips input prompt, uses hardcoded demo prompt."""
    from turnzero.cli.setup import _DEMO_PROMPT, _print_setup_finale

    captured: list[str] = []

    def fake_render(prompt: str) -> None:
        captured.append(prompt)

    monkeypatch.setattr("turnzero.cli.setup._render_demo_results", fake_render)
    _print_setup_finale(interactive=False)
    assert captured == [_DEMO_PROMPT]


def test_finale_interactive_empty_input_uses_demo_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive + empty Enter → falls back to demo prompt."""
    from turnzero.cli.base import console
    from turnzero.cli.setup import _DEMO_PROMPT, _print_setup_finale

    captured: list[str] = []

    def _capture(p: str) -> None:
        captured.append(p)

    monkeypatch.setattr("turnzero.cli.setup._render_demo_results", _capture)
    monkeypatch.setattr(console, "input", lambda _prompt: "")
    _print_setup_finale(interactive=True)
    assert captured == [_DEMO_PROMPT]


def test_finale_interactive_custom_prompt_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive + typed prompt → that prompt is used for retrieval."""
    from turnzero.cli.base import console
    from turnzero.cli.setup import _print_setup_finale

    captured: list[str] = []

    def _capture(p: str) -> None:
        captured.append(p)

    monkeypatch.setattr("turnzero.cli.setup._render_demo_results", _capture)
    monkeypatch.setattr(console, "input", lambda _prompt: "debugging a Python asyncio deadlock")
    _print_setup_finale(interactive=True)
    assert captured == ["debugging a Python asyncio deadlock"]


def test_finale_interactive_eoferror_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """EOFError (non-TTY / piped input) → silent fallback to demo prompt."""
    from turnzero.cli.base import console
    from turnzero.cli.setup import _DEMO_PROMPT, _print_setup_finale

    captured: list[str] = []

    def _capture(p: str) -> None:
        captured.append(p)

    def _raise(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("turnzero.cli.setup._render_demo_results", _capture)
    monkeypatch.setattr(console, "input", _raise)
    _print_setup_finale(interactive=True)
    assert captured == [_DEMO_PROMPT]


# ---------------------------------------------------------------------------
# RET-8: domain management
# ---------------------------------------------------------------------------


def test_get_active_domains_returns_none_when_absent(tmp_path: Path) -> None:
    from turnzero.config import get_active_domains
    assert get_active_domains(tmp_path) is None


def test_get_active_domains_returns_list_when_set(tmp_path: Path) -> None:
    import yaml

    from turnzero.config import get_active_domains
    (tmp_path / "config.yaml").write_text(yaml.dump({"active_domains": ["python", "docker"]}))
    assert get_active_domains(tmp_path) == ["python", "docker"]


def test_domain_add_initialises_from_defaults(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from turnzero.config import DEFAULT_ACTIVE_DOMAINS, get_active_domains
    result = runner.invoke(app, ["domain", "add", "langchain"])
    assert result.exit_code == 0
    active = get_active_domains(data_dir)
    assert active is not None
    assert "langchain" in active
    # default set also present
    assert "python" in active
    assert len(active) == len(set(DEFAULT_ACTIVE_DOMAINS) | {"langchain"})


def test_domain_add_existing_set(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from turnzero.config import get_active_domains
    (data_dir / "config.yaml").write_text(yaml.dump({"active_domains": ["python", "docker"]}))
    result = runner.invoke(app, ["domain", "add", "fastapi"])
    assert result.exit_code == 0
    active = get_active_domains(data_dir)
    assert active is not None
    assert set(active) == {"python", "docker", "fastapi"}


def test_domain_add_duplicate_is_idempotent(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from turnzero.config import get_active_domains
    (data_dir / "config.yaml").write_text(yaml.dump({"active_domains": ["python"]}))
    runner.invoke(app, ["domain", "add", "python"])
    assert get_active_domains(data_dir) == ["python"]


def test_domain_remove(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from turnzero.config import get_active_domains
    (data_dir / "config.yaml").write_text(yaml.dump({"active_domains": ["python", "docker"]}))
    result = runner.invoke(app, ["domain", "remove", "docker"])
    assert result.exit_code == 0
    assert get_active_domains(data_dir) == ["python"]


def test_domain_remove_last_domain_errors(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml
    (data_dir / "config.yaml").write_text(yaml.dump({"active_domains": ["python"]}))
    result = runner.invoke(app, ["domain", "remove", "python"])
    assert result.exit_code != 0


def test_domain_reset(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from turnzero.config import DEFAULT_ACTIVE_DOMAINS, get_active_domains
    (data_dir / "config.yaml").write_text(yaml.dump({"active_domains": ["python"]}))
    result = runner.invoke(app, ["domain", "reset"])
    assert result.exit_code == 0
    assert get_active_domains(data_dir) == list(DEFAULT_ACTIVE_DOMAINS)


def test_retrieval_svc_no_filter_when_active_domains_none(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """active_domains=None → all blocks pass through (backward compat)."""
    import turnzero.services.retrieval_svc as rsvc
    from turnzero.blocks import Block

    def _fake_blocks() -> dict[str, Block]:
        return {
            "py-block": Block(slug="py-block", hash="h", version="1", domain="python",
                              intent="build", last_verified="2026-01-01", tags=[], context_weight=100,
                              constraints=[], anti_patterns=[], doc_anchors=[], conflicts_with=[],
                              conflicts_with_tags=[], provides=[], requires=[], confidence=1.0,
                              verification_level="curated", rationale=None, archived=False, tier="community"),
            "k8s-block": Block(slug="k8s-block", hash="h", version="1", domain="kubernetes",
                               intent="build", last_verified="2026-01-01", tags=[], context_weight=100,
                               constraints=[], anti_patterns=[], doc_anchors=[], conflicts_with=[],
                               conflicts_with_tags=[], provides=[], requires=[], confidence=1.0,
                               verification_level="curated", rationale=None, archived=False, tier="community"),
        }

    monkeypatch.setattr(rsvc, "_load_active_blocks", _fake_blocks)
    # No config.yaml → active_domains=None → both blocks should reach query()
    captured_blocks: list = []
    def _fake_query(prompt, index, blocks, **kw):  # type: ignore[no-untyped-def]
        captured_blocks.extend(blocks.keys())
        return []
    monkeypatch.setattr(rsvc, "_query", _fake_query)
    monkeypatch.setattr(rsvc, "_load_active_index", lambda: [])
    monkeypatch.setattr(rsvc, "get_session_injections", lambda _: set())
    import turnzero.retrieval as ret
    monkeypatch.setattr(ret, "get_identity_context", lambda blocks, **kw: ([], False))
    import turnzero.services.stats_svc as ssvc
    monkeypatch.setattr(ssvc, "log_injection", lambda **kw: None)
    import turnzero.telemetry as tel
    monkeypatch.setattr(tel, "track_session_start", lambda **kw: None)
    rsvc.list_suggested_blocks("build something", session_id=None)
    assert "py-block" in captured_blocks
    assert "k8s-block" in captured_blocks


# ---------------------------------------------------------------------------
# RET-9: day-2 re-engagement nudge
# ---------------------------------------------------------------------------


def test_stats_nudge_shown_when_setup_done_no_sessions(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml
    # Simulate setup completed: telemetry.yaml has anonymous_id
    (data_dir / "telemetry.yaml").write_text(
        yaml.dump({"enabled": True, "anonymous_id": "test-uuid-1234"})
    )
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "No sessions logged yet" in result.output
    assert "turnzero list" in result.output


def test_stats_nudge_not_shown_when_setup_not_done(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No telemetry.yaml → setup not done
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "No sessions logged yet" not in result.output


def test_stats_nudge_not_shown_when_sessions_exist(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml
    (data_dir / "telemetry.yaml").write_text(
        yaml.dump({"enabled": True, "anonymous_id": "test-uuid-5678"})
    )
    _write_hook_log(data_dir, 3)
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "No sessions logged yet" not in result.output


# ---------------------------------------------------------------------------
# UX-2: personal-tier blocks show as "personal / always-on" in domain table
# ---------------------------------------------------------------------------


def test_list_domain_summary_personal_shown_as_always_on(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks_dir = data_dir / "blocks"
    (blocks_dir / "community" / "fastapi").mkdir(parents=True)
    _write_test_block(
        blocks_dir / "community" / "fastapi" / "fastapi-build.yaml",
        "fastapi-build", "fastapi",
    )
    personal_dir = blocks_dir / "personal" / "global"
    personal_dir.mkdir(parents=True)
    _write_test_block(
        personal_dir / "my-pref-build.yaml",
        "my-pref-build", "global",
    )
    import turnzero.cli.discovery as disc
    monkeypatch.setattr(disc, "get_blocks_dir", lambda: blocks_dir)

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "personal" in result.output
    assert "always-on" in result.output
    # "global" should NOT appear as an inactive domain
    assert "inactive" not in result.output


# ---------------------------------------------------------------------------
# GRW-2: turnzero contribute
# ---------------------------------------------------------------------------


def test_contribute_unknown_block_id_exits(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (data_dir / "candidates").mkdir()
    result = runner.invoke(app, ["contribute", "nonexistent-block"])
    assert result.exit_code != 0


def test_contribute_fallback_when_gh_missing(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import turnzero.cli.contribute as contrib
    cand_dir = data_dir / "candidates"
    cand_dir.mkdir()
    (cand_dir / "my-rule-build.yaml").write_text(
        "slug: my-rule-build\ndomain: python\n"
    )
    monkeypatch.setattr(contrib.shutil, "which", lambda _: None)
    result = runner.invoke(app, ["contribute", "my-rule-build"])
    assert result.exit_code == 0
    assert "github.com/turnzero-ai/turnzero/issues/new" in result.output


def test_contribute_with_gh_opens_issue(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import turnzero.cli.contribute as contrib
    cand_dir = data_dir / "candidates"
    cand_dir.mkdir()
    (cand_dir / "my-rule-build.yaml").write_text(
        "slug: my-rule-build\ndomain: python\n"
    )
    monkeypatch.setattr(contrib.shutil, "which", lambda _: "/usr/bin/gh")
    calls: list[list[str]] = []
    def _fake_run(cmd: list[str], **kw: object) -> None:
        calls.append(cmd)
    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = runner.invoke(app, ["contribute", "my-rule-build"])
    assert result.exit_code == 0
    assert calls and "gh" in calls[0][0]
    assert any("my-rule-build" in arg for arg in calls[0])


# ---------------------------------------------------------------------------
# TEL-2: domain_changed telemetry fires on add / remove / reset
# ---------------------------------------------------------------------------


def test_domain_add_fires_telemetry(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, telemetry_spy: list
) -> None:
    import yaml

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {}})
    )

    runner.invoke(app, ["domain", "add", "rust"])
    domain_events = [e for e in telemetry_spy if e["event"] == "domain_changed"]
    assert domain_events
    assert domain_events[0]["action"] == "add"
    assert domain_events[0]["domain"] == "rust"


def test_domain_remove_fires_telemetry(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, telemetry_spy: list
) -> None:
    import yaml

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python", "rust"], "sources": {}})
    )

    runner.invoke(app, ["domain", "remove", "rust"])
    domain_events = [e for e in telemetry_spy if e["event"] == "domain_changed"]
    assert domain_events
    assert domain_events[0]["action"] == "remove"
    assert domain_events[0]["domain"] == "rust"


def test_domain_reset_fires_telemetry(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, telemetry_spy: list
) -> None:
    runner.invoke(app, ["domain", "reset"])
    domain_events = [e for e in telemetry_spy if e["event"] == "domain_changed"]
    assert domain_events
    assert domain_events[0]["action"] == "reset"
