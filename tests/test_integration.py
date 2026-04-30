"""Integration tests — end-to-end pipelines that don't call a live AI API.

Learning loop:  submit_candidate -> index rebuild -> list_suggested_blocks returns the new block
Harvest:        fixture conversation + mocked LLM -> parse -> write -> block retrievable
Injection seq:  list_suggested_blocks -> inject_block -> formatted text is coherent
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from turnzero.harvest import (
    load_conversation,
    parse_candidates,
    validate_candidate,
    write_candidate,
)
from turnzero.mcp_server import (
    _inject_block,
    _list_suggested_blocks,
    submit_candidate,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _use_test_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURNZERO_TEST_EMBEDDINGS", "1")

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _seed_data_dir(tmp_path: Path) -> None:
    """Copy bundled blocks + build index into tmp_path so tests have a real library."""
    from turnzero.index import build as build_index

    pkg_blocks = Path(__file__).parent.parent / "turnzero" / "data" / "blocks"
    repo_blocks = Path(__file__).parent.parent / "data" / "blocks"
    src = pkg_blocks if pkg_blocks.exists() else repo_blocks

    dest_blocks = tmp_path / "blocks"
    shutil.copytree(src, dest_blocks)
    build_index(dest_blocks, tmp_path / "index.jsonl", data_dir=tmp_path)


# ===========================================================================
# 1. Learning loop — submit_candidate -> retrieve
# ===========================================================================

class TestLearningLoop:
    """Covers the core promise: corrections become retrievable priors immediately."""

    def test_submitted_block_is_retrievable(self, tmp_path: Path) -> None:
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            result = submit_candidate(
                block_id="django-orm-select-related-build",
                domain="django",
                intent="build",
                constraints=[
                    "Use select_related() for ForeignKey traversals to avoid N+1 queries",
                    "Use prefetch_related() for ManyToMany and reverse FK relations",
                ],
                anti_patterns=[
                    "Do not access related objects in a loop without prefetching -- causes N+1 queries",
                ],
                rationale="Iterating over related objects without prefetching causes a database hit per iteration (N+1 problem). select_related joins at the SQL level, while prefetch_related batches the second query.",
                tags=["django", "orm", "performance"],
                reason="AI suggested iterating querysets without select_related",
                auto_approve=True,
            )

            assert "added to local library" in result
            assert "django-orm-select-related-build" in result

            suggestions = _list_suggested_blocks(
                "building a Django app with ORM queries across related models",
                strict_intent=False,
                threshold=0.50,
            )
            ids = [s["block_id"] for s in suggestions]
            assert "django-orm-select-related-build" in ids, (
                f"Submitted block not found in suggestions. Got: {ids}"
            )
        finally:
            del os.environ["TURNZERO_DATA_DIR"]

    def test_submitted_block_scores_above_threshold(self, tmp_path: Path) -> None:
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            submit_candidate(
                block_id="stripe-webhook-verify-build",
                domain="stripe",
                intent="build",
                constraints=[
                    "Always verify Stripe webhook signatures using stripe.Webhook.construct_event()",
                    "Use the raw request body for signature verification -- do not parse JSON first",
                ],
                anti_patterns=[
                    "Do not skip webhook signature verification -- allows spoofed events",
                ],
                rationale="Stripe webhook verification ensures the event came from Stripe. Using the raw body is critical because JSON parsing can change the byte representation, causing signature mismatches.",
                tags=["stripe", "webhooks", "security"],
                auto_approve=True,
            )

            results = _list_suggested_blocks(
                "building a Stripe payment webhook handler that verifies signatures",
                strict_intent=False,
                threshold=0.50,
            )
            match = next(
                (r for r in results if r["block_id"] == "stripe-webhook-verify-build"), None
            )
            assert match is not None, "stripe-webhook-verify-build not retrieved"
            assert match["score"] >= 0.50

        finally:
            del os.environ["TURNZERO_DATA_DIR"]

    def test_queued_block_not_retrievable(self, tmp_path: Path) -> None:
        """auto_approve=False must NOT make the block retrievable."""
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            submit_candidate(
                block_id="queued-only-block-build",
                domain="django",
                intent="build",
                constraints=["queued block should not appear in retrieval"],
                anti_patterns=["Do not expect queued blocks in results"],
                rationale="Testing that unapproved candidates are excluded from retrieval results.",
                auto_approve=False,
            )

            results = _list_suggested_blocks(
                "queued block retrieval test for django orm",
                strict_intent=False,
                threshold=0.0,
            )
            ids = [r["block_id"] for r in results]
            assert "queued-only-block-build" not in ids

        finally:
            del os.environ["TURNZERO_DATA_DIR"]

    def test_no_duplicates_after_submit(self, tmp_path: Path) -> None:
        """Submitting a block twice must not produce duplicate results."""
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            for _ in range(2):
                submit_candidate(
                    block_id="dedup-test-block-build",
                    domain="fastapi",
                    intent="build",
                    constraints=["Use async def for all route handlers in FastAPI"],
                    anti_patterns=["Do not use sync def for IO-bound FastAPI routes"],
                    rationale="In FastAPI, sync def routes are run in a thread pool, while async def routes run directly on the event loop. sync def is for blocking CPU work; async def is for IO.",
                    auto_approve=True,
                )

            results = _list_suggested_blocks(
                "building a FastAPI async REST API with route handlers",
                strict_intent=False,
                threshold=0.50,
            )
            ids = [r["block_id"] for r in results]
            assert ids.count("dedup-test-block-build") <= 1, (
                f"Duplicate block_id in results: {ids}"
            )
        finally:
            del os.environ["TURNZERO_DATA_DIR"]


# ===========================================================================
# 2. Harvest pipeline — fixture conversation + mocked LLM -> retrievable block
# ===========================================================================

# Realistic FastAPI+SQLAlchemy session with a mid-session correction
_FIXTURE_CONVERSATION = (
    "User: I'm building a FastAPI app with SQLAlchemy async sessions. "
    "I'm getting connection pool exhaustion errors after a few hundred requests.\n\n"
    "Assistant: The most common cause is not closing sessions. "
    "Make sure you use a context manager: with Session() as session: ...\n\n"
    "User: I'm already doing that. I use async_session = sessionmaker(..., class_=AsyncSession). "
    "Each route creates a session with async with async_session() as session.\n\n"
    "Assistant: In that case the issue is likely that you're creating a new engine per request. "
    "Move engine creation outside the request handler.\n\n"
    "User: No, the engine is a module-level singleton. "
    "Actually I think the problem is pool_size. I set pool_size=5 but the docs say "
    "async engines need pool_pre_ping=True and you should set pool_size based on "
    "your worker count times connections per worker.\n\n"
    "Assistant: You're right. For async SQLAlchemy with FastAPI you should set "
    "pool_size = workers * max_connections_per_worker, enable pool_pre_ping=True "
    "to detect stale connections, and set max_overflow=0 if you want strict limits.\n\n"
    "User: And don't forget that NullPool is required when using pgBouncer in "
    "transaction mode -- using a connection pool on top of pgBouncer causes issues.\n\n"
    "Assistant: Correct. When pgBouncer is in transaction mode, use "
    "create_async_engine(url, poolclass=NullPool) to disable SQLAlchemy's pool entirely."
)

# The YAML a well-behaved LLM would return for the fixture conversation above
_MOCK_LLM_YAML = """\
- id: sqlalchemy-async-pool-build
  version: "1.0.0"
  domain: sqlalchemy
  intent: build
  last_verified: "2026-01-01"
  tags:
    - sqlalchemy
    - async
    - fastapi
    - postgresql
  context_weight: 200
  conflicts_with: []
  requires: []
  constraints:
    - Set pool_pre_ping=True on async engines to detect stale connections
    - Size pool_size based on worker_count * max_connections_per_worker
    - Use NullPool (poolclass=NullPool) when connecting through pgBouncer in transaction mode
  anti_patterns:
    - Do not use a SQLAlchemy connection pool on top of pgBouncer in transaction mode -- causes pool exhaustion
    - Do not create a new engine per request -- engine must be a module-level singleton
  rationale: |
    SQLAlchemy's built-in pooling conflicts with pgBouncer's transaction mode.
    pool_pre_ping is necessary to avoid stale connection errors.
    Engine singletons prevent connection leaks.
  doc_anchors: []
"""


class TestHarvestPipeline:
    """Covers: mocked LLM extraction -> parse -> validate -> write -> index -> retrieve."""

    def test_parse_candidates_from_mock_yaml(self) -> None:
        """parse_candidates must return well-formed dicts from the mock YAML."""
        candidates = parse_candidates(_MOCK_LLM_YAML)
        assert len(candidates) == 1
        c = candidates[0]
        assert c["id"] == "sqlalchemy-async-pool-build"
        assert c["domain"] == "sqlalchemy"
        assert c["intent"] == "build"
        assert len(c["constraints"]) == 3
        assert len(c["anti_patterns"]) == 2

    def test_validate_candidate_passes_good_block(self) -> None:
        """validate_candidate must return None (no error) for a well-formed block."""
        candidates = parse_candidates(_MOCK_LLM_YAML)
        error = validate_candidate(candidates[0])
        assert error is None, f"validate_candidate rejected a good block: {error}"

    def test_write_candidate_creates_yaml_file(self, tmp_path: Path) -> None:
        """write_candidate must produce a readable YAML file with the correct id."""
        import yaml as _yaml

        candidates = parse_candidates(_MOCK_LLM_YAML)
        blocks_dir = tmp_path / "blocks" / "local"
        blocks_dir.mkdir(parents=True)

        path = write_candidate(candidates[0], blocks_dir)

        assert path.exists()
        loaded = _yaml.safe_load(path.read_text())
        assert loaded["id"] == "sqlalchemy-async-pool-build"

    def test_harvest_end_to_end_with_mocked_llm(self, tmp_path: Path) -> None:
        """Full harvest pipeline: fixture conversation -> mocked LLM -> write -> index -> retrieve."""
        from turnzero.index import build as build_index

        # Write fixture conversation to a temp file
        conv_file = tmp_path / "session.md"
        conv_file.write_text(_FIXTURE_CONVERSATION, encoding="utf-8")

        # Seed data dir with bundled blocks
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            # Mock extract_with_llm to return our controlled YAML
            with patch("turnzero.harvest.extract_with_llm", return_value=_MOCK_LLM_YAML):
                from turnzero.harvest import harvest
                candidates = harvest(conv_file, tmp_path / "blocks" / "local")

            assert len(candidates) == 1
            assert candidates[0]["id"] == "sqlalchemy-async-pool-build"

            # Write the candidate and rebuild index
            blocks_dir = tmp_path / "blocks" / "local"
            blocks_dir.mkdir(parents=True, exist_ok=True)
            write_candidate(candidates[0], blocks_dir)
            build_index(tmp_path / "blocks", tmp_path / "index.jsonl", data_dir=tmp_path)

            # Block must now be retrievable — use domain-specific query, high top_k so
            # the newly indexed block can compete against the seeded fastapi bundles
            results = _list_suggested_blocks(
                "SQLAlchemy async pool_pre_ping pgBouncer NullPool connection pool",
                strict_intent=False,
                threshold=0.0,
                top_k=20,
            )
            ids = [r["block_id"] for r in results]
            assert "sqlalchemy-async-pool-build" in ids, (
                f"Harvested block not found in suggestions. Got: {ids}"
            )
        finally:
            del os.environ["TURNZERO_DATA_DIR"]

    def test_load_conversation_reads_plain_text(self, tmp_path: Path) -> None:
        """load_conversation must return the raw text for a plain .txt file."""
        conv_file = tmp_path / "session.txt"
        conv_file.write_text(_FIXTURE_CONVERSATION, encoding="utf-8")
        text = load_conversation(conv_file)
        assert "pgBouncer" in text
        assert "pool_pre_ping" in text


# ===========================================================================
# 3. Injection sequence — list_suggested_blocks -> inject_block -> coherent text
# ===========================================================================

class TestInjectionSequence:
    """Covers the injection UX: retrieve -> inject -> formatted output is valid."""

    def test_inject_block_returns_formatted_text(self, tmp_path: Path) -> None:
        """inject_block must return non-empty formatted text for a known block."""
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            # Pick the first block from the seeded library
            suggestions = _list_suggested_blocks(
                "building a web application with API endpoints",
                strict_intent=False,
                threshold=0.0,
            )
            assert suggestions, "No blocks in seeded library"

            block_id = suggestions[0]["block_id"]
            text = _inject_block(block_id)

            assert text, f"inject_block returned empty string for {block_id}"
            assert len(text) > 20
        finally:
            del os.environ["TURNZERO_DATA_DIR"]

    def test_inject_unknown_block_raises_value_error(self, tmp_path: Path) -> None:
        """inject_block must raise ValueError with a helpful message for an unknown block id."""
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)
            with pytest.raises(ValueError, match="not found"):
                _inject_block("this-block-does-not-exist-build")
        finally:
            del os.environ["TURNZERO_DATA_DIR"]

    def test_list_then_inject_pipeline_is_coherent(self, tmp_path: Path) -> None:
        """list_suggested_blocks -> inject_block must produce output containing constraints."""
        os.environ["TURNZERO_DATA_DIR"] = str(tmp_path)
        try:
            _seed_data_dir(tmp_path)

            # Submit a known block so we can assert on its content
            submit_candidate(
                block_id="react-hooks-deps-build",
                domain="react",
                intent="build",
                constraints=[
                    "Always include all values referenced inside useEffect in the dependency array",
                    "Use useCallback to stabilise function references passed as effect dependencies",
                ],
                anti_patterns=[
                    "Do not suppress exhaustive-deps eslint warnings -- they indicate real bugs",
                ],
                rationale="Missing dependencies in useEffect cause stale closures and bugs. useCallback prevents unnecessary re-renders when functions are used as dependencies.",
                tags=["react", "hooks"],
                auto_approve=True,
            )

            suggestions = _list_suggested_blocks(
                "building a React component with useEffect and custom hooks",
                strict_intent=False,
                threshold=0.50,
            )
            ids = [s["block_id"] for s in suggestions]
            assert "react-hooks-deps-build" in ids, f"react-hooks-deps-build not suggested. Got: {ids}"

            text = _inject_block("react-hooks-deps-build")
            assert "useEffect" in text or "dependency" in text.lower() or "useCallback" in text
        finally:
            del os.environ["TURNZERO_DATA_DIR"]
