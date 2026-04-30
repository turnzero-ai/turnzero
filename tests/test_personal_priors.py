"""Tests for Personal Priors always-on injection and budget limits."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from turnzero.mcp_server import _list_suggested_blocks
from turnzero.retrieval import MAX_PERSONAL_WEIGHT


@pytest.fixture
def mock_data(tmp_path: Path):
    blocks_dir = tmp_path / "blocks"
    personal_dir = blocks_dir / "personal" / "global"
    personal_dir.mkdir(parents=True)

    # 1. A standard personal workflow prior
    workflow_path = personal_dir / "workflow.yaml"
    workflow_path.write_text(
        """
slug: workflow-standard
domain: global
intent: build
version: 1.0.0
last_verified: "2026-04-29"
context_weight: 500
constraints: ["Use conventional commits"]
anti_patterns: []
doc_anchors: []
""",
        encoding="utf-8",
    )

    # 2. A domain-specific personal prior
    python_dir = blocks_dir / "personal" / "python"
    python_dir.mkdir(parents=True)
    python_path = python_dir / "python-prefs.yaml"
    python_path.write_text(
        """
slug: python-prefs
domain: python
intent: build
version: 1.0.0
last_verified: "2026-04-29"
context_weight: 500
constraints: ["Always use mypy strict"]
anti_patterns: []
doc_anchors: []
""",
        encoding="utf-8",
    )

    # 3. A project root with a python indicator
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[tool.poetry]", encoding="utf-8")

    return {
        "blocks_dir": blocks_dir,
        "project_root": project_root,
    }


def test_personal_priors_always_on_even_with_empty_prompt(mock_data, monkeypatch):
    """Personal priors should be returned even for generic prompts like 'hi', regardless of domain."""
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(mock_data["blocks_dir"].parent))

    with (
        patch("turnzero.mcp_server._blocks_dir", return_value=mock_data["blocks_dir"]),
        patch("turnzero.mcp_server._load_active_index", return_value=[]),
        patch("turnzero.mcp_server.get_session_injections", return_value=set()),
    ):
        # Prompt is generic and project is empty/unknown
        results = _list_suggested_blocks(
            "hi", project_root=Path("/tmp/nonexistent-project")
        )

        slugs = [r["block_id"] for r in results]
        assert "workflow-standard" in slugs  # Global personal prior
        assert "python-prefs" in slugs  # Domain-specific prior now also auto-injected
        # Verify they have top scores
        for r in results:
            if r["block_id"] in ("workflow-standard", "python-prefs"):
                assert r["score"] == 2.0


def test_personal_priors_budget_limit_and_warning(mock_data, monkeypatch):
    """If personal priors exceed the budget, they should be truncated and a warning added."""
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(mock_data["blocks_dir"].parent))

    # Add a giant personal prior to exceed the 2500 limit
    big_prior_path = mock_data["blocks_dir"] / "personal" / "global" / "giant.yaml"
    big_prior_path.write_text(
        f"""
slug: giant-prior
domain: global
intent: build
version: 1.0.0
last_verified: "2026-04-30"
context_weight: {MAX_PERSONAL_WEIGHT + 100}
constraints: ["Too many rules"]
anti_patterns: []
doc_anchors: []
""",
        encoding="utf-8",
    )

    with (
        patch("turnzero.mcp_server._blocks_dir", return_value=mock_data["blocks_dir"]),
        patch("turnzero.mcp_server._load_active_index", return_value=[]),
        patch("turnzero.mcp_server.get_session_injections", return_value=set()),
    ):
        results = _list_suggested_blocks("hi", project_root=mock_data["project_root"])

        slugs = [r["block_id"] for r in results]
        # Giant prior was verified 2026-04-30 (newest), but it exceeds the budget alone.
        # 2600 is NOT <= 2500. So giant is dropped.
        # Then next are workflow (500) and python (500). Total 1000 <= 2500.

        assert "workflow-standard" in slugs
        assert "python-prefs" in slugs
        assert "giant-prior" not in slugs
        assert "personal-priors-limit-warning" in slugs
