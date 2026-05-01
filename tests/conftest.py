import pytest


@pytest.fixture(autouse=True)
def _use_test_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Automatically use hash-based test embeddings for all tests."""
    monkeypatch.setenv("TURNZERO_TEST_EMBEDDINGS", "1")
