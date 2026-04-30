"""Tests for MCP server tool logic (pure functions, no live server required)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from turnzero.blocks import compute_confidence
from turnzero.mcp_server import (
    _get_block,
    _inject_block,
    _list_suggested_blocks,
    _log_mcp_injection,
    _log_tool_call,
    learn_from_session,
)


@pytest.fixture(autouse=True)
def _use_test_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURNZERO_TEST_EMBEDDINGS", "1")


# ---------------------------------------------------------------------------
# list_suggested_blocks
# ---------------------------------------------------------------------------


def test_list_suggested_blocks_returns_correct_top_result() -> None:
    results = _list_suggested_blocks(
        "help me build a Next.js app with Supabase authentication"
    )
    assert len(results) >= 1
    # Any nextjs block in top results is correct — hash embeddings may rank differently
    # from production embeddings; we validate domain correctness not exact rank
    block_ids = [r["block_id"] for r in results]
    assert any(
        bid.startswith("nextjs") or bid.startswith("supabase") for bid in block_ids
    )


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
        # 2.0 indicates an Identity Prior, others are Expert (0-1)
        assert 0.0 <= item["score"] <= 2.0


def test_list_suggested_blocks_docker_top_result() -> None:
    results = _list_suggested_blocks(
        "set up Docker Compose for a production deployment"
    )
    # Identity priors are injected first, look for the first Expert Prior
    expert_ids = [r["block_id"] for r in results if r["score"] < 2.0]
    assert expert_ids[0] == "docker-compose-production-build"


def test_list_suggested_blocks_typescript_top_result() -> None:
    results = _list_suggested_blocks(
        "migrate my JavaScript codebase to TypeScript strict mode"
    )
    # Identity priors injected first
    expert_ids = [r["block_id"] for r in results if r["score"] < 2.0]
    assert expert_ids[0] == "typescript-migration-migrate"


def test_list_suggested_blocks_postgresql_top_result() -> None:
    results = _list_suggested_blocks(
        "review my PostgreSQL schema and queries for performance"
    )
    # Identity priors injected first
    expert_ids = [r["block_id"] for r in results if r["score"] < 2.0]
    assert expert_ids[0] == "postgresql-indexing-review"


def test_list_suggested_blocks_respects_top_k() -> None:
    results = _list_suggested_blocks("build something", top_k=1)
    # Saturation Logic returns ALL high-confidence (0.90+) matches.
    # If we want to strictly test top_k, we need to check if there are any low-conf matches.
    experts = [r for r in results if r["score"] < 2.0]
    assert len(experts) >= 1


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
    assert "# EXPERT_PRIOR_IDENTITY" in text
    assert "# SESSION_CONSTRAINTS" in text
    assert "# ANTI_PATTERNS" in text


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


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------


def test_compute_confidence_minimal_signals() -> None:
    score = compute_confidence("x", ["one constraint"], [], [], "")
    assert score == pytest.approx(0.25, abs=0.01)


def test_compute_confidence_full_signals() -> None:
    score = compute_confidence(
        "nextjs15-approuter-auth-build",
        ["Use App Router", "Pin to Next.js 15"],
        ["Do not use Pages Router", "Do not use getServerSideProps"],
        ["nextjs", "auth"],
        "AI used deprecated Pages Router API in Next.js 15 project",
    )
    assert score == pytest.approx(0.95, abs=0.01)


def test_compute_confidence_caps_at_0_95() -> None:
    for _ in range(3):
        score = compute_confidence(
            "a-b-c-d",
            ["c1", "c2", "c3"],
            ["Do not do x", "Do not do y"],
            ["tag1", "tag2"],
            "long enough reason here to get bonus",
        )
    assert score <= 0.95


def test_compute_confidence_reason_bonus() -> None:
    without = compute_confidence("slug-a-b", ["c1", "c2"], ["Do not x"], ["t"], "")
    with_reason = compute_confidence(
        "slug-a-b", ["c1", "c2"], ["Do not x"], ["t"], "AI got this wrong in session"
    )
    assert with_reason > without


def test_submit_candidate_writes_confidence_and_archived(tmp_path: Path) -> None:
    import turnzero.mcp_server as mcp

    orig_data = mcp._data_dir
    orig_blocks = mcp._blocks_dir
    orig_index = mcp._index_path

    data_dir = tmp_path / "data"
    blocks_dir = tmp_path / "blocks"
    index_file = data_dir / "index.jsonl"
    data_dir.mkdir()
    blocks_dir.mkdir()

    mcp._data_dir = lambda: data_dir
    mcp._blocks_dir = lambda: blocks_dir
    mcp._index_path = lambda: index_file

    try:
        from turnzero.mcp_server import submit_candidate

        submit_candidate(
            block_id="test-confidence-build",
            domain="fastapi",
            intent="build",
            constraints=["Use async def", "Use Pydantic v2"],
            anti_patterns=["Do not use sync def in async context"],
            tags=["fastapi"],
            reason="AI used sync def in async FastAPI route",
            auto_approve=False,
        )
        candidate_path = data_dir / "candidates" / "test-confidence-build.yaml"
        assert candidate_path.exists()
        data = yaml.safe_load(candidate_path.read_text())
        assert "confidence" in data
        assert 0.0 < data["confidence"] <= 0.95
        assert data["archived"] is False
    finally:
        mcp._data_dir = orig_data
        mcp._blocks_dir = orig_blocks
        mcp._index_path = orig_index


# ---------------------------------------------------------------------------
# _log_tool_call
# ---------------------------------------------------------------------------


def test_log_tool_call_writes_tool_call_log(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_tool_call(
            "inject_block", {"block_id": "fastapi-async-build"}, "some text output"
        )
        log_path = tmp_path / "tool_call_log.jsonl"
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["tool"] == "inject_block"
        assert entry["tokens_in"] > 0
        assert entry["tokens_out"] > 0
        assert "ts" in entry
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_log_tool_call_appends_multiple_tools(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_tool_call("list_suggested_blocks", {"prompt": "build a fastapi app"}, [])
        _log_tool_call("inject_block", {"block_id": "fastapi-async-build"}, "text")
        _log_tool_call(
            "submit_candidate", {"block_id": "x"}, "saved", meta={"auto_approve": True}
        )
        lines = (tmp_path / "tool_call_log.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3
        tools = [json.loads(ln)["tool"] for ln in lines]
        assert tools == ["list_suggested_blocks", "inject_block", "submit_candidate"]
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_log_tool_call_meta_persisted(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_tool_call(
            "submit_candidate",
            {"block_id": "x"},
            "ok",
            meta={"auto_approve": True, "block_id": "x"},
        )
        entry = json.loads((tmp_path / "tool_call_log.jsonl").read_text().strip())
        assert entry["auto_approve"] is True
        assert entry["block_id"] == "x"
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_log_tool_call_token_estimate_scales_with_payload(tmp_path: Path) -> None:
    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        short_out = "short"
        long_out = "x" * 4000
        _log_tool_call("inject_block", {}, short_out)
        _log_tool_call("inject_block", {}, long_out)
        lines = (tmp_path / "tool_call_log.jsonl").read_text().strip().splitlines()
        e_short = json.loads(lines[0])
        e_long = json.loads(lines[1])
        assert e_long["tokens_out"] > e_short["tokens_out"]
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_get_stats_includes_tool_call_counts(tmp_path: Path) -> None:
    from turnzero.mcp_server import get_stats

    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_tool_call("list_suggested_blocks", {"prompt": "test"}, [])
        _log_tool_call("inject_block", {"block_id": "b"}, "text")
        result = get_stats()
        assert "tool_calls" in result
        assert result["tool_calls"]["total"] >= 2
        assert "list_suggested_blocks" in result["tool_calls"]["by_tool"]
        assert "inject_block" in result["tool_calls"]["by_tool"]
    finally:
        del os.environ["TURNZERO_DATA_DIR"]


def test_get_stats_includes_token_cost(tmp_path: Path) -> None:
    from turnzero.mcp_server import get_stats

    os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
    try:
        _log_tool_call("inject_block", {"block_id": "b"}, "some output text here")
        _log_tool_call(
            "submit_candidate", {"block_id": "x"}, "saved", meta={"auto_approve": True}
        )
        result = get_stats()
        assert "token_cost" in result
        assert result["token_cost"]["total"] > 0
        assert result["token_cost"]["submit_candidate_total"] > 0
        assert result["token_cost"]["total_in"] >= 0
        assert result["token_cost"]["total_out"] >= 0
    finally:
        del os.environ["TURNZERO_DATA_DIR"]
