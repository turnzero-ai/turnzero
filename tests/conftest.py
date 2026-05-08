from __future__ import annotations

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
