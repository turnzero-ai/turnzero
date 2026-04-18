"""Tests for MCP server tool logic (pure functions, no live server required)."""

from __future__ import annotations

import pytest

from turnzero.mcp_server import _get_block, _inject_block, _list_suggested_blocks

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
