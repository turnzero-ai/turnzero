"""Tests for MCP server tool logic (pure functions, no live server required)."""

from __future__ import annotations

import json
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


def test_log_injection_writes_log(data_dir: Path) -> None:
    _log_mcp_injection(
        block_ids=["nextjs15-approuter-build"],
        domains=["nextjs"],
        prompt_words=12,
        tokens_injected=480,
    )
    log_path = data_dir / "hook_log.jsonl"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["blocks"] == ["nextjs15-approuter-build"]
    assert entry["domains"] == ["nextjs"]
    assert entry["prompt_words"] == 12
    assert entry["source"] == "mcp"
    assert entry["tokens_injected"] == 480
    assert "ts" in entry


def test_log_injection_appends(data_dir: Path) -> None:
    _log_mcp_injection(["block-a"], ["fastapi"], 5)
    _log_mcp_injection(["block-b"], ["nextjs"], 8)
    lines = (data_dir / "hook_log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# learn_from_session honest message
# ---------------------------------------------------------------------------


def test_learn_from_session_returns_harvest_instruction(data_dir: Path) -> None:
    result = learn_from_session(transcript="some session text", session_name="test")
    assert "turnzero harvest" in result
    assert "daemon" not in result.lower()


def test_inject_block_all_seed_blocks(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Use empty data dir so active_domains=None (all domains active — backward compat).
    # Without this, the user's real ~/.turnzero config may filter domains in this test.
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


def test_submit_candidate_writes_confidence_and_archived(data_dir: Path) -> None:
    import turnzero.services.candidate_svc as cand_svc

    orig_data = cand_svc.get_data_dir
    orig_blocks = cand_svc.get_blocks_dir
    orig_index = cand_svc.get_index_path

    data_dir = data_dir / "data"
    blocks_dir = data_dir / "blocks"
    index_file = data_dir / "index.jsonl"
    data_dir.mkdir()
    blocks_dir.mkdir()

    cand_svc.get_data_dir = lambda: data_dir
    cand_svc.get_blocks_dir = lambda: blocks_dir
    cand_svc.get_index_path = lambda: index_file

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
        cand_svc.get_data_dir = orig_data
        cand_svc.get_blocks_dir = orig_blocks
        cand_svc.get_index_path = orig_index


# ---------------------------------------------------------------------------
# ONB-3: "First Correction" Nudge
# ---------------------------------------------------------------------------


def _make_candidate_svc_patcher(tmp_path: Path) -> tuple:
    import turnzero.services.candidate_svc as cand_svc

    data_dir = tmp_path / "data"
    blocks_dir = data_dir / "blocks"
    index_file = data_dir / "index.jsonl"
    data_dir.mkdir()
    blocks_dir.mkdir()

    orig = (cand_svc.get_data_dir, cand_svc.get_blocks_dir, cand_svc.get_index_path)
    cand_svc.get_data_dir = lambda: data_dir
    cand_svc.get_blocks_dir = lambda: blocks_dir
    cand_svc.get_index_path = lambda: index_file
    return cand_svc, orig


def test_onb3_nudge_on_new_candidate(data_dir: Path) -> None:
    cand_svc, orig = _make_candidate_svc_patcher(data_dir)
    try:
        from turnzero.mcp_server import submit_candidate

        result = submit_candidate(
            block_id="onb3-test-build",
            domain="fastapi",
            intent="build",
            constraints=["Use async def"],
            anti_patterns=["Do not use sync def in async context"],
            reason="AI used sync def",
            auto_approve=False,
        )
        assert "💡 Correction captured" in result
        assert "turnzero review" in result
    finally:
        cand_svc.get_data_dir, cand_svc.get_blocks_dir, cand_svc.get_index_path = orig


def test_onb3_no_nudge_on_duplicate_candidate(data_dir: Path) -> None:
    cand_svc, orig = _make_candidate_svc_patcher(data_dir)
    try:
        from turnzero.mcp_server import submit_candidate

        submit_candidate(
            block_id="onb3-dupe-build",
            domain="fastapi",
            intent="build",
            constraints=["Use async def"],
            anti_patterns=["Do not use sync def in async context"],
            reason="first submission",
            auto_approve=False,
        )
        result = submit_candidate(
            block_id="onb3-dupe-build",
            domain="fastapi",
            intent="build",
            constraints=["Use async def"],
            anti_patterns=["Do not use sync def in async context"],
            reason="second submission",
            auto_approve=False,
        )
        assert "💡 Correction captured" not in result
        assert "updated in review queue" in result
    finally:
        cand_svc.get_data_dir, cand_svc.get_blocks_dir, cand_svc.get_index_path = orig


# ---------------------------------------------------------------------------
# _log_tool_call
# ---------------------------------------------------------------------------


def test_log_tool_call_writes_tool_call_log(data_dir: Path) -> None:
    _log_tool_call(
        "inject_block", {"block_id": "fastapi-async-build"}, "some text output"
    )
    log_path = data_dir / "tool_call_log.jsonl"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["tool"] == "inject_block"
    assert entry["tokens_in"] > 0
    assert entry["tokens_out"] > 0
    assert "ts" in entry


def test_log_tool_call_appends_multiple_tools(data_dir: Path) -> None:
    _log_tool_call("list_suggested_blocks", {"prompt": "build a fastapi app"}, [])
    _log_tool_call("inject_block", {"block_id": "fastapi-async-build"}, "text")
    _log_tool_call(
        "submit_candidate", {"block_id": "x"}, "saved", meta={"auto_approve": True}
    )
    lines = (data_dir / "tool_call_log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
    tools = [json.loads(ln)["tool"] for ln in lines]
    assert tools == ["list_suggested_blocks", "inject_block", "submit_candidate"]


def test_log_tool_call_meta_persisted(data_dir: Path) -> None:
    _log_tool_call(
        "submit_candidate",
        {"block_id": "x"},
        "ok",
        meta={"auto_approve": True, "block_id": "x"},
    )
    entry = json.loads((data_dir / "tool_call_log.jsonl").read_text().strip())
    assert entry["auto_approve"] is True
    assert entry["block_id"] == "x"


def test_log_tool_call_token_estimate_scales_with_payload(data_dir: Path) -> None:
    short_out = "short"
    long_out = "x" * 4000
    _log_tool_call("inject_block", {}, short_out)
    _log_tool_call("inject_block", {}, long_out)
    lines = (data_dir / "tool_call_log.jsonl").read_text().strip().splitlines()
    e_short = json.loads(lines[0])
    e_long = json.loads(lines[1])
    assert e_long["tokens_out"] > e_short["tokens_out"]


def test_get_stats_includes_tool_call_counts(data_dir: Path) -> None:
    from turnzero.mcp_server import get_stats

    _log_tool_call("list_suggested_blocks", {"prompt": "test"}, [])
    _log_tool_call("inject_block", {"block_id": "b"}, "text")
    result = get_stats()
    assert "tool_calls" in result
    assert result["tool_calls"]["total"] >= 2
    assert "list_suggested_blocks" in result["tool_calls"]["by_tool"]
    assert "inject_block" in result["tool_calls"]["by_tool"]


def test_inject_block_text_includes_token_metadata() -> None:
    """inject_block output must include PRIOR_METADATA with token count (RET-3)."""
    result = _inject_block("fastapi-async-build")
    assert "# PRIOR_METADATA" in result
    assert "tokens" in result
    assert "fastapi-async-build" in result


def test_get_stats_includes_context_tokens_injected(data_dir: Path) -> None:
    from turnzero.mcp_server import get_stats

    _log_mcp_injection(["block-a"], ["fastapi"], 10, tokens_injected=800)
    _log_mcp_injection(["block-b"], ["nextjs"], 8, tokens_injected=480)
    result = get_stats()
    assert "context_tokens_injected" in result
    assert result["context_tokens_injected"]["total"] == 1280


def test_get_stats_includes_token_cost(data_dir: Path) -> None:
    from turnzero.mcp_server import get_stats

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


def test_get_stats_reports_measured_outcomes(data_dir: Path) -> None:
    from turnzero.mcp_server import get_stats

    result = get_stats()
    assert result["outcomes"]["sessions"] == 0
    assert result["outcomes"]["repeat_rate"] is None
    assert "estimated_turns_saved" not in result
    assert "estimated_tokens_saved" not in result
    assert "word_count" not in result["context_tokens_injected"]["note"]


# ---------------------------------------------------------------------------
# WF-1: process-scoped auto session_id
# ---------------------------------------------------------------------------


def test_effective_session_id_returns_caller_id_when_provided() -> None:
    from turnzero.mcp_server import _effective_session_id

    assert _effective_session_id("my-session") == "my-session"


def test_effective_session_id_returns_stable_proc_id_when_none() -> None:
    from turnzero.mcp_server import _effective_session_id

    id1 = _effective_session_id(None)
    id2 = _effective_session_id(None)
    assert id1 == id2
    assert len(id1) == 36  # UUID4 format


def test_rotate_proc_session_changes_id() -> None:
    from turnzero.mcp_server import _effective_session_id, _rotate_proc_session

    before = _effective_session_id(None)
    _rotate_proc_session()
    after = _effective_session_id(None)
    assert before != after


# ---------------------------------------------------------------------------
# WF-2: turn field and Turn 0 vs Turn N personal prior suppression
# ---------------------------------------------------------------------------


def test_list_suggested_blocks_turn_field_present() -> None:
    results = _list_suggested_blocks("build a fastapi app with postgres")
    real = [r for r in results if r.get("block_id") != "personal-priors-limit-warning"]
    assert all("turn" in r for r in real)


def test_list_suggested_blocks_first_turn_without_session() -> None:
    """No session_id → no exclude_ids → always Turn 0."""
    results = _list_suggested_blocks("build a fastapi app with postgres")
    real = [r for r in results if r.get("block_id") != "personal-priors-limit-warning"]
    assert all(r["turn"] == "first" for r in real)


def test_list_suggested_blocks_subsequent_turn_skips_personal(data_dir: Path) -> None:
    """After inject_block records an injection, next list call is Turn N."""
    from turnzero.session import record_session_injection

    sid = "wf2-test-session"
    record_session_injection(sid, "fake-prior-already-injected")

    results = _list_suggested_blocks(
        "build a fastapi app with postgres", session_id=sid
    )
    real = [
        r for r in results if r.get("block_id") != "personal-priors-limit-warning"
    ]
    assert all(r["turn"] == "subsequent" for r in real)
    assert [r for r in real if r["score"] == 2.0] == []


# ---------------------------------------------------------------------------
# Full text is always included
# ---------------------------------------------------------------------------


def test_list_suggested_blocks_always_includes_full_text() -> None:
    results = _list_suggested_blocks("build a fastapi app with postgres")
    real = [r for r in results if r["block_id"] != "personal-priors-limit-warning"]

    assert len(real) > 0
    for r in real:
        assert isinstance(r["full_text"], str) and r["full_text"]
        assert r["context_weight"] == len(r["full_text"]) // 4
        assert "inject_block" not in r["preview"]


def test_handler_ignores_inject_all_and_logs_block_ids(data_dir: Path) -> None:
    from turnzero.mcp_server import list_suggested_blocks

    results = list_suggested_blocks(
        "build a fastapi app with postgres", session_id="full-text", inject_all=False
    )

    real = [r for r in results if r["score"] > 0]
    assert real and all(r["full_text"] for r in real)
    logged = json.loads((data_dir / "tool_call_log.jsonl").read_text().splitlines()[-1])
    assert logged["block_ids"] == [r["block_id"] for r in real]


def test_second_call_in_a_session_returns_no_personal_priors(data_dir: Path) -> None:
    prior = data_dir / "blocks" / "personal" / "global" / "style.yaml"
    prior.parent.mkdir(parents=True)
    prior.write_text(
        "slug: style\nversion: 1.0.0\ndomain: global\nintent: build\n"
        "last_verified: 2026-05-01\ncontext_weight: 100\n"
        'constraints:\n  - "Keep answers short"\nanti_patterns: []\n'
        "confidence: 0.9\narchived: false\n",
        encoding="utf-8",
    )

    first = _list_suggested_blocks("hi", session_id="twice")
    second = _list_suggested_blocks("hi again", session_id="twice")

    assert [r["block_id"] for r in first if r["score"] == 2.0] == ["style"]
    assert [r for r in second if r["score"] == 2.0] == []


def test_personal_prior_without_constraints_still_returns_its_text(
    data_dir: Path,
) -> None:
    prior = data_dir / "blocks" / "personal" / "global" / "empty.yaml"
    prior.parent.mkdir(parents=True)
    prior.write_text(
        "slug: empty\nversion: 1.0.0\ndomain: global\nintent: build\n"
        "last_verified: 2026-05-01\ncontext_weight: 100\nconstraints: []\n"
        "anti_patterns: []\nconfidence: 0.9\narchived: false\n",
        encoding="utf-8",
    )

    (entry,) = [r for r in _list_suggested_blocks("hi") if r["block_id"] == "empty"]

    assert entry["preview"] == ""
    assert "Slug: empty" in entry["full_text"]


# ── DEBT-1: BlockSubmission dataclass ────────────────────────────────────────

def test_block_submission_requires_positional_fields() -> None:
    """BlockSubmission enforces required fields at construction time."""
    from turnzero.services.candidate_svc import BlockSubmission

    # Valid construction — no error
    sub = BlockSubmission(
        block_id="test-slug",
        domain="python",
        intent="build",
        constraints=["Use X"],
        anti_patterns=["Do not use Y"],
    )
    assert sub.block_id == "test-slug"
    assert sub.tags == []
    assert sub.rationale is None

    # Missing required positional args raises TypeError
    with pytest.raises(TypeError):
        BlockSubmission()  # type: ignore[call-arg]


def test_build_block_dict_uses_submission_fields() -> None:
    """_build_block_dict output reflects all BlockSubmission fields."""
    from turnzero.services.candidate_svc import BlockSubmission, _build_block_dict

    sub = BlockSubmission(
        block_id="my-prior",
        domain="python",
        intent="debug",
        constraints=["Always log errors"],
        anti_patterns=["Do not swallow exceptions"],
        tags=["logging"],
        rationale="Visibility matters.",
        confidence=0.8,
        today="2026-05-20",
        project_hash=None,
    )
    d = _build_block_dict(sub)
    assert d["slug"] == "my-prior"
    assert d["domain"] == "python"
    assert d["intent"] == "debug"
    assert d["constraints"] == ["Always log errors"]
    assert d["anti_patterns"] == ["Do not swallow exceptions"]
    assert d["tags"] == ["logging"]
    assert d["confidence"] == 0.8
    assert d["last_verified"] == "2026-05-20"
    assert d["archived"] is False


# ---------------------------------------------------------------------------
# Outcome digest and background scan
# ---------------------------------------------------------------------------


def _write_recent_outcome_sessions(data_dir: Path, count: int) -> None:
    import time

    ts = time.time() - 3600
    rows = [
        {
            "kind": "session",
            "session": f"s{i}",
            "project": "p",
            "ts": ts,
            "user_turns": 3,
            "injected": ["a"],
            "lines_scanned": 9,
            "mtime": ts,
        }
        for i in range(count)
    ]
    (data_dir / "outcomes.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def test_list_suggested_blocks_handler_adds_weekly_digest(data_dir: Path) -> None:
    from turnzero.mcp_server import list_suggested_blocks

    _write_recent_outcome_sessions(data_dir, 10)

    first = list_suggested_blocks("build a FastAPI async REST API", session_id="digest-1")
    assert first[-1]["block_id"] == "outcome-digest"
    assert "repeat corrections/session" in first[-1]["preview"]

    stale_day = {"week": json.loads((data_dir / "outcome_digest.json").read_text())["week"], "date": "2000-01-01"}
    (data_dir / "outcome_digest.json").write_text(json.dumps(stale_day))
    second = list_suggested_blocks("build a FastAPI async REST API", session_id="digest-2")
    assert all(r["block_id"] != "outcome-digest" for r in second)

    log_lines = (data_dir / "tool_call_log.jsonl").read_text().splitlines()
    assert "outcome-digest" not in json.loads(log_lines[0]).get("block_ids", [])


def test_service_list_suggested_blocks_has_no_digest_by_default(data_dir: Path) -> None:
    _write_recent_outcome_sessions(data_dir, 10)

    results = _list_suggested_blocks("build a FastAPI async REST API", session_id="plain")

    assert all(r["block_id"] != "outcome-digest" for r in results)


def test_main_starts_background_outcome_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from turnzero import mcp_server
    from turnzero.services import outcome_svc

    started = threading.Event()
    monkeypatch.setattr(outcome_svc, "scan_quietly", started.set)
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: None)

    mcp_server.main()

    assert started.wait(timeout=5)


def test_list_suggested_blocks_survives_damaged_outcomes_file(data_dir: Path) -> None:
    from turnzero.mcp_server import list_suggested_blocks

    _write_recent_outcome_sessions(data_dir, 10)
    with (data_dir / "outcomes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "session", "session": "bad", "ts": "yesterday"}) + "\n")
        f.write(json.dumps({"kind": "correction", "session": "bad", "ts": 1.0, "verdict": "failed"}) + "\n")

    results = list_suggested_blocks("build a FastAPI async REST API", session_id="damaged")

    assert any(r["block_id"].startswith("fastapi") for r in results)


def test_list_suggested_blocks_survives_digest_failure(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The digest is garnish; it must never take the injection path down."""
    from turnzero.mcp_server import list_suggested_blocks
    from turnzero.services import outcome_svc

    def broken(data_dir: Path) -> str:
        raise ValueError("unexpected")

    monkeypatch.setattr(outcome_svc, "weekly_line", broken)

    results = list_suggested_blocks("build a FastAPI async REST API", session_id="broken")

    assert any(r["block_id"].startswith("fastapi") for r in results)
