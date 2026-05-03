from __future__ import annotations

import pytest

import turnzero.retrieval as _retrieval
from tests.fixtures.similarity import test_similarity


@pytest.fixture(autouse=True)
def _use_test_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use hash-based embeddings and lexical similarity override for all tests."""
    monkeypatch.setenv("TURNZERO_TEST_EMBEDDINGS", "1")
    monkeypatch.setattr(_retrieval, "_similarity_override", test_similarity)
