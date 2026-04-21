"""Tests for MCP server tool logic (pure functions, no live server required)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from turnzero.mcp_server import (
    _get_block,
    _inject_block,
    _list_suggested_blocks,
    _log_mcp_injection,
    learn_from_session,
)

# ---------------------------------------------------------------------------
# list_suggested_blocks
# ---------------------------------------------------------------------------

def test_list_suggested_blocks_returns_correct_top_result() -> None:
    results = _list_suggested_blocks(
        "help me build a Next.js app with Supabase authentication"
    )
    assert len(results) >= 1
    assert results[0]["block_id"].startswith("nextjs15-approuter-build")


def test_list_suggested_blocks_result_shape() -> None:
    results = _list_suggested_blocks("build a FastAPI async REST API")
    assert len(results) >= 1
    first = results[0]
    assert "block_id" in first
    assert "score" in first
    assert "domain" in first
    assert "intent" in first
    assert "tags" in first
    assert "context_weight" in first
    assert "stale" in first
    assert "preview" in first


def test_list_suggested_blocks_scores_in_range() -> None:
    results = _list_suggested_blocks("set up Docker Compose for production")
    for item in results:
        assert 0.0 <= item["score"] <= 1.0


def test_list_suggested_blocks_docker_top_result() -> None:
    results = _list_suggested_blocks("set up Docker Compose for a production deployment")
    assert results[0]["block_id"] == "docker-compose-production-build"


def test_list_suggested_blocks_typescript_top_result() -> None:
    results = _list_suggested_blocks(
        "migrate my JavaScript codebase to TypeScript strict mode"
    )
    # With strict intent (True by default), this should find the migrate block
    assert results[0]["block_id"] == "typescript-migration-migrate"


def test_list_suggested_blocks_postgresql_top_result() -> None:
    results = _list_suggested_blocks(
        "review my PostgreSQL schema and queries for performance"
    )
    # With strict intent, this should find the review block
    assert results[0]["block_id"] == "postgresql-indexing-review"


def test_list_suggested_blocks_respects_top_k() -> None:
    results = _list_suggested_blocks("build something", top_k=1)
    assert len(results) <= 1


def test_list_suggested_blocks_high_threshold_returns_fewer() -> None:
    results_low = _list_suggested_blocks("build a Next.js app", threshold=0.40)
    results_high = _list_suggested_blocks("build a Next.js app", threshold=0.95)
    assert len(results_low) >= len(results_high)


def test_list_suggested_blocks_unknown_prompt_graceful() -> None:
    # Should not raise — may return empty list
    results = _list_suggested_blocks("xyzzy florp bleep noop", threshold=0.99)
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# get_block
# ---------------------------------------------------------------------------

def test_get_block_returns_correct_fields() -> None:
    data = _get_block("nextjs15-approuter-build")
    assert data["id"] == "nextjs15-approuter-build"
    assert data["domain"] == "nextjs"
    assert data["intent"] == "build"
    assert isinstance(data["constraints"], list)
    assert isinstance(data["anti_patterns"], list)
    assert isinstance(data["doc_anchors"], list)
    assert isinstance(data["tags"], list)
    assert isinstance(data["context_weight"], int)
    assert isinstance(data["stale"], bool)


def test_get_block_doc_anchors_shape() -> None:
    data = _get_block("nextjs15-approuter-build")
    assert len(data["doc_anchors"]) > 0
    for anchor in data["doc_anchors"]:
        assert "url" in anchor
        assert "verified" in anchor


def test_get_block_not_found_raises_value_error() -> None:
    with pytest.raises(ValueError, match="not found"):
        _get_block("nonexistent-block-id")


def test_get_block_error_lists_available() -> None:
    with pytest.raises(ValueError, match="nextjs15-approuter-build"):
        _get_block("nonexistent-block-id")


# ---------------------------------------------------------------------------
# inject_block
# ---------------------------------------------------------------------------

def test_inject_block_returns_markdown() -> None:
    text = _inject_block("nextjs15-approuter-build")
    assert "## Expert Prior:" in text
    assert "Constraints:" in text
    assert "Anti-patterns" in text


def test_inject_block_contains_block_id() -> None:
    text = _inject_block("fastapi-async-build")
    assert "fastapi-async-build" in text


def test_inject_block_not_found_raises_value_error() -> None:
    with pytest.raises(ValueError, match="not found"):
        _inject_block("nonexistent-block-id")


# ---------------------------------------------------------------------------
# deduplication
# ---------------------------------------------------------------------------

def test_list_suggested_blocks_no_duplicates() -> None:
    results = _list_suggested_blocks(
        "Build a Next.js 15 app router page that fetches data from an API and deploys on Vercel"
    )
    ids = [r["block_id"] for r in results]
    assert len(ids) == len(set(ids)), f"Duplicate block_ids returned: {ids}"


# ---------------------------------------------------------------------------
# MCP injection logging
# ---------------------------------------------------------------------------

def test_log_mcp_injection_writes_hook_log(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_mcp_injection(
            block_ids=["nextjs15-approuter-build"],
            domains=["nextjs"],
            prompt_words=12,
        )
        log_path = tmp_path / "hook_log.jsonl"
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["blocks"] == ["nextjs15-approuter-build"]
        assert entry["domains"] == ["nextjs"]
        assert entry["prompt_words"] == 12
        assert entry["source"] == "mcp"
        assert "ts" in entry
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_log_mcp_injection_appends(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_mcp_injection(["block-a"], ["fastapi"], 5)
        _log_mcp_injection(["block-b"], ["nextjs"], 8)
        lines = (tmp_path / "hook_log.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


# ---------------------------------------------------------------------------
# learn_from_session honest message
# ---------------------------------------------------------------------------

def test_learn_from_session_returns_harvest_instruction(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        result = learn_from_session(transcript="some session text", session_name="test")
        assert "turnzero harvest" in result
        assert "daemon" not in result.lower()
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_inject_block_all_seed_blocks() -> None:
    seed_ids = [
        "nextjs15-approuter-build",
        "supabase-auth-pkce-build",
        "fastapi-async-build",
        "typescript-strict-build",
        "postgresql-patterns-build",
        "docker-compose-production-build",
        "react-native-expo-build",
        "langchain-lcel-build",
    ]
    for block_id in seed_ids:
        text = _inject_block(block_id)
        assert len(text) > 100, f"{block_id}: injection text too short"
