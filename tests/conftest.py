from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import turnzero.retrieval as _retrieval
from tests.fixtures.similarity import test_similarity


@pytest.fixture(autouse=True)
def _use_test_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use hash-based embeddings and lexical similarity override for all tests."""
    monkeypatch.setenv("TURNZERO_TEST_EMBEDDINGS", "1")
    monkeypatch.setattr(_retrieval, "_similarity_override", test_similarity)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated data directory with TURNZERO_DATA_DIR env var set."""
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def quiet_console() -> Console:
    """Rich Console that suppresses all output during tests."""
    return Console(quiet=True)


@pytest.fixture
def telemetry_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture all track_event calls without hitting PostHog."""
    import turnzero.telemetry as tel
    fired: list[dict[str, Any]] = []
    monkeypatch.setattr(tel, "track_event", lambda e, p: fired.append({"event": e, **p}))
    return fired


# ---------------------------------------------------------------------------
# TST-1: Block factory
# ---------------------------------------------------------------------------

@pytest.fixture
def make_block() -> Callable[..., Any]:
    """Factory for Block instances with sensible defaults."""
    from turnzero.blocks import Block

    def _factory(
        slug: str,
        domain: str,
        *,
        tier: str = "community",
        intent: str = "build",
        confidence: float = 1.0,
        archived: bool = False,
        last_verified: str = "2026-01-01",
        constraints: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Block:
        return Block(
            slug=slug,
            hash="h",
            version="1.0.0",
            domain=domain,
            intent=intent,
            last_verified=last_verified,
            tags=tags or [],
            context_weight=100,
            constraints=constraints or ["Do the thing"],
            anti_patterns=[],
            doc_anchors=[],
            confidence=confidence,
            verification_level="curated",
            rationale=None,
            archived=archived,
            tier=tier,
        )

    return _factory


# ---------------------------------------------------------------------------
# TST-2: Block YAML writer
# ---------------------------------------------------------------------------

@pytest.fixture
def write_block_yaml() -> Callable[..., Path]:
    """Write a minimal valid block YAML file. Returns the path written."""

    def _factory(
        path: Path,
        slug: str,
        domain: str,
        *,
        stale: bool = False,
        confidence: float = 0.9,
        archived: bool = False,
        intent: str = "build",
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        verified = "2020-01-01" if stale else "2026-05-01"
        path.write_text(
            f"slug: {slug}\nversion: 1.0.0\ndomain: {domain}\nintent: {intent}\n"
            f"last_verified: {verified}\ncontext_weight: 100\nconstraints: []\n"
            f"anti_patterns: []\nconfidence: {confidence}\narchived: {'true' if archived else 'false'}\n"
        )
        return path

    return _factory


# ---------------------------------------------------------------------------
# TST-4: Stats shape assertion
# ---------------------------------------------------------------------------

def assert_stats_shape(data: dict[str, Any], required_keys: list[str]) -> None:
    """Assert all required keys are present in a stats dict."""
    missing = [k for k in required_keys if k not in data]
    assert not missing, f"Stats dict missing keys: {missing}"
