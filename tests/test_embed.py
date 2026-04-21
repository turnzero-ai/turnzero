"""Tests for embed.py backend fallback chain."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from turnzero.embed import EMBEDDING_DIM, _embed_ollama, _embed_openai, embed

# ---------------------------------------------------------------------------
# _embed_ollama — uses httpx directly, no ollama package required
# ---------------------------------------------------------------------------

def _fake_ollama_response(embedding: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"embedding": embedding}
    resp.raise_for_status.return_value = None
    return resp


def test_embed_ollama_uses_httpx_not_ollama_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """ollama backend must work without the ollama Python package installed."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    vec = list(range(EMBEDDING_DIM))
    with patch("httpx.post", return_value=_fake_ollama_response(vec)) as mock_post:
        result = _embed_ollama("test prompt")

    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "localhost:11434" in url
    assert mock_post.call_args[1]["json"]["model"] == "nomic-embed-text"
    assert result.shape == (EMBEDDING_DIM,)
    assert result.dtype == np.float32


def test_embed_ollama_respects_ollama_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://my-server:12345")

    vec = list(range(EMBEDDING_DIM))
    with patch("httpx.post", return_value=_fake_ollama_response(vec)) as mock_post:
        _embed_ollama("test prompt")

    url = mock_post.call_args[0][0]
    assert "my-server:12345" in url
    assert "localhost" not in url


def test_embed_ollama_host_without_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "my-server:12345")

    vec = list(range(EMBEDDING_DIM))
    with patch("httpx.post", return_value=_fake_ollama_response(vec)) as mock_post:
        _embed_ollama("test prompt")

    url = mock_post.call_args[0][0]
    assert url.startswith("http://my-server:12345")


def test_embed_ollama_raises_runtime_error_on_failure() -> None:
    with patch("httpx.post", side_effect=Exception("connection refused")), \
         pytest.raises(RuntimeError, match="ollama unavailable"):
        _embed_ollama("test prompt")


# ---------------------------------------------------------------------------
# _embed_openai — uses httpx, no openai package required
# ---------------------------------------------------------------------------

def _fake_openai_response(embedding: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"data": [{"embedding": embedding}]}
    resp.raise_for_status.return_value = None
    return resp


def test_embed_openai_uses_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    vec = [0.1] * EMBEDDING_DIM
    with patch("httpx.post", return_value=_fake_openai_response(vec)) as mock_post:
        result = _embed_openai("test prompt")

    mock_post.assert_called_once()
    assert "openai.com" in mock_post.call_args[0][0]
    assert result.shape == (EMBEDDING_DIM,)


# ---------------------------------------------------------------------------
# embed() fallback chain
# ---------------------------------------------------------------------------

def test_embed_falls_back_to_openai_when_ollama_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    vec = [0.5] * EMBEDDING_DIM

    with patch("turnzero.embed._embed_ollama", side_effect=RuntimeError("ollama down")), \
         patch("turnzero.embed._embed_sentence_transformers", side_effect=RuntimeError("no st")), \
         patch("turnzero.embed._embed_openai", return_value=np.array(vec, dtype=np.float32)) as mock_openai:
        result = embed("test")

    mock_openai.assert_called_once()
    assert result.shape == (EMBEDDING_DIM,)


def test_embed_raises_when_no_backend_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("turnzero.embed._embed_ollama", side_effect=RuntimeError("down")), \
         patch("turnzero.embed._embed_sentence_transformers", side_effect=RuntimeError("not installed")), \
         pytest.raises(RuntimeError, match="No embedding backend available"):
        embed("test prompt")


def test_embed_skips_openai_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("turnzero.embed._embed_ollama", side_effect=RuntimeError("down")), \
         patch("turnzero.embed._embed_sentence_transformers", side_effect=RuntimeError("not installed")), \
         patch("turnzero.embed._embed_openai") as mock_openai, \
         pytest.raises(RuntimeError):
        embed("test")

    mock_openai.assert_not_called()
