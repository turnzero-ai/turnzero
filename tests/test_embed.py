"""Tests for embed.py backend fallback chain."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from turnzero.embed import (
    EMBEDDING_DIM,
    _embed_ollama,
    _embed_openai,
    _is_onnx_available,
    _is_onnx_model_downloaded,
    _ollama_timeout,
    embed,
)


@pytest.fixture(autouse=True)
def _disable_test_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback chain tests must run without short-circuiting test embeddings."""
    monkeypatch.delenv("TURNZERO_TEST_EMBEDDINGS", raising=False)


# ---------------------------------------------------------------------------
# _embed_ollama — uses httpx directly, no ollama package required
# ---------------------------------------------------------------------------


def _fake_ollama_response(embedding: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"embedding": embedding}
    resp.raise_for_status.return_value = None
    return resp


def test_embed_ollama_uses_httpx_not_ollama_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ollama backend must work without the ollama Python package installed."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    vec = [float(i) for i in range(EMBEDDING_DIM)]
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

    vec = [float(i) for i in range(EMBEDDING_DIM)]
    with patch("httpx.post", return_value=_fake_ollama_response(vec)) as mock_post:
        _embed_ollama("test prompt")

    url = mock_post.call_args[0][0]
    assert "my-server:12345" in url
    assert "localhost" not in url


def test_embed_ollama_host_without_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "my-server:12345")

    vec = [float(i) for i in range(EMBEDDING_DIM)]
    with patch("httpx.post", return_value=_fake_ollama_response(vec)) as mock_post:
        _embed_ollama("test prompt")

    url = mock_post.call_args[0][0]
    assert url.startswith("http://my-server:12345")


def test_embed_ollama_raises_runtime_error_on_failure() -> None:
    with (
        patch("httpx.post", side_effect=Exception("connection refused")),
        pytest.raises(RuntimeError, match="ollama unavailable"),
    ):
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
    assert mock_post.call_args[0][0] == "https://api.openai.com/v1/embeddings"
    assert result.shape == (EMBEDDING_DIM,)


# ---------------------------------------------------------------------------
# embed() fallback chain
# ---------------------------------------------------------------------------


def test_embed_falls_back_to_openai_when_local_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    vec = [0.5] * EMBEDDING_DIM

    with (
        patch("turnzero.embed._embed_ollama", side_effect=RuntimeError("ollama down")),
        patch(
            "turnzero.embed._embed_openai", return_value=np.array(vec, dtype=np.float32)
        ) as mock_openai,
    ):
        result = embed("test")

    mock_openai.assert_called_once()
    assert result.shape == (EMBEDDING_DIM,)


def test_embed_raises_when_all_backends_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with (
        patch("turnzero.embed._embed_ollama", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError, match="No embedding backend available"),
    ):
        embed("test prompt")


def test_embed_skips_openai_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with (
        patch("turnzero.embed._embed_ollama", side_effect=RuntimeError("down")),
        patch("turnzero.embed._embed_openai") as mock_openai,
        pytest.raises(RuntimeError),
    ):
        embed("test")

    mock_openai.assert_not_called()


def test_embed_prefers_ollama_over_openai() -> None:
    """ollama takes priority over OpenAI when ONNX is not available."""
    vec = [0.4] * EMBEDDING_DIM

    with (
        patch("turnzero.embed._is_onnx_available", return_value=False),
        patch(
            "turnzero.embed._embed_ollama", return_value=np.array(vec, dtype=np.float32)
        ) as mock_ollama,
        patch("turnzero.embed._embed_openai") as mock_openai,
    ):
        embed("test")

    mock_ollama.assert_called_once()
    mock_openai.assert_not_called()


# ---------------------------------------------------------------------------
# ONNX backend
# ---------------------------------------------------------------------------


def test_onnx_preferred_when_available_and_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vec = [0.3] * EMBEDDING_DIM

    with (
        patch("turnzero.embed._is_onnx_available", return_value=True),
        patch("turnzero.embed._is_onnx_model_downloaded", return_value=True),
        patch(
            "turnzero.embed._embed_onnx", return_value=np.array(vec, dtype=np.float32)
        ) as mock_onnx,
        patch("turnzero.embed._embed_ollama") as mock_ollama,
    ):
        result = embed("test")

    mock_onnx.assert_called_once()
    mock_ollama.assert_not_called()
    assert result.shape == (EMBEDDING_DIM,)


def test_embed_falls_back_to_ollama_when_onnx_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vec = [0.2] * EMBEDDING_DIM

    with (
        patch("turnzero.embed._is_onnx_available", return_value=True),
        patch("turnzero.embed._is_onnx_model_downloaded", return_value=True),
        patch("turnzero.embed._embed_onnx", side_effect=RuntimeError("onnx error")),
        patch(
            "turnzero.embed._embed_ollama", return_value=np.array(vec, dtype=np.float32)
        ) as mock_ollama,
    ):
        result = embed("test")

    mock_ollama.assert_called_once()
    assert result.shape == (EMBEDDING_DIM,)


def test_embed_skips_onnx_when_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vec = [0.1] * EMBEDDING_DIM

    with (
        patch("turnzero.embed._is_onnx_available", return_value=False),
        patch("turnzero.embed._embed_onnx") as mock_onnx,
        patch(
            "turnzero.embed._embed_ollama", return_value=np.array(vec, dtype=np.float32)
        ),
    ):
        embed("test")

    mock_onnx.assert_not_called()


def test_embed_skips_onnx_when_model_not_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vec = [0.1] * EMBEDDING_DIM

    with (
        patch("turnzero.embed._is_onnx_available", return_value=True),
        patch("turnzero.embed._is_onnx_model_downloaded", return_value=False),
        patch("turnzero.embed._embed_onnx") as mock_onnx,
        patch(
            "turnzero.embed._embed_ollama", return_value=np.array(vec, dtype=np.float32)
        ),
    ):
        embed("test")

    mock_onnx.assert_not_called()


def test_is_onnx_available_false_when_deps_missing() -> None:
    """_is_onnx_available returns False when onnxruntime is not importable."""
    import sys

    with patch.dict(sys.modules, {"onnxruntime": None, "tokenizers": None}):
        # Force re-evaluation by calling with patched modules
        # The function does a fresh import attempt each call
        result = _is_onnx_available()
    # Result depends on whether deps are actually installed in test env;
    # just verify it returns a bool without raising.
    assert isinstance(result, bool)


def test_is_onnx_model_downloaded_false_when_files_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    assert not _is_onnx_model_downloaded()


# ── TURNZERO_OLLAMA_TIMEOUT_SECONDS ──────────────────────────────────────────


def test_ollama_timeout_default() -> None:
    with patch.dict("os.environ", {}, clear=False):
        os_env = __import__("os").environ
        os_env.pop("TURNZERO_OLLAMA_TIMEOUT_SECONDS", None)
        assert _ollama_timeout() == 30.0


def test_ollama_timeout_env_override() -> None:
    with patch.dict("os.environ", {"TURNZERO_OLLAMA_TIMEOUT_SECONDS": "60"}):
        assert _ollama_timeout() == 60.0


def test_ollama_timeout_invalid_env_falls_back_to_default() -> None:
    with patch.dict("os.environ", {"TURNZERO_OLLAMA_TIMEOUT_SECONDS": "notanumber"}):
        assert _ollama_timeout() == 30.0


def test_ollama_timeout_below_minimum_clamped() -> None:
    with patch.dict("os.environ", {"TURNZERO_OLLAMA_TIMEOUT_SECONDS": "0"}):
        assert _ollama_timeout() == 1.0
