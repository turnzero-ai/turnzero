"""Embedding with backend fallback and cosine similarity."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

import numpy as np

# Dimension produced by nomic-embed-text. All backends are normalised to this.
EMBEDDING_DIM = 768
HTTP_OK = 200


def get_model_id() -> str:
    """Return the ID of the current active embedding model."""
    if os.environ.get("TURNZERO_TEST_EMBEDDINGS") == "1":
        return "test-hash-blake2b-768"

    # We check environment before calling Ollama to avoid silent timeout wait
    if os.environ.get("OPENAI_API_KEY") and not _is_ollama_running():
        return "openai:text-embedding-3-small"

    # Default local model
    return "ollama:nomic-embed-text"


def _is_ollama_running() -> bool:
    """Fast check if ollama is responsive."""
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        with httpx.Client(timeout=0.5) as client:
            return client.get(f"{host}/api/tags").status_code == HTTP_OK
    except Exception:
        return False


def embed(text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Embed text, returning a float32 ndarray of shape (768,).

    Fallback chain:
      1. ollama nomic-embed-text       (local server, fastest if already running)
      2. OpenAI text-embedding-3-small (cloud, OPENAI_API_KEY)

    Everything runs locally by default. No text leaves the machine unless
    OPENAI_API_KEY is explicitly set.
    """
    try:
        return _embed_ollama(text)
    except RuntimeError:
        pass

    if os.environ.get("TURNZERO_TEST_EMBEDDINGS") == "1":
        return _embed_test(text)

    if os.environ.get("OPENAI_API_KEY"):
        return _embed_openai(text)

    raise RuntimeError(
        "No embedding backend available.\n\n"
        "Or use a local server:\n"
        "  ollama serve && ollama pull nomic-embed-text\n\n"
        "Or use OpenAI:\n"
        "  export OPENAI_API_KEY=sk-..."
    )


def _embed_ollama(text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not host.startswith("http"):
        host = f"http://{host}"

    try:
        resp = httpx.post(
            f"{host}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=10.0,
        )
        resp.raise_for_status()
        return np.array(resp.json()["embedding"], dtype=np.float32)
    except Exception as e:
        raise RuntimeError(f"ollama unavailable: {e}") from e


def _embed_test(text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Deterministic local embedding used only in tests."""
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]
    for idx, token in enumerate(tokens):
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        slot = int.from_bytes(h[:4], "little") % EMBEDDING_DIM
        vec[slot] += 1.0
        if idx:
            bigram = f"{tokens[idx - 1]}::{token}"
            hb = hashlib.blake2b(bigram.encode("utf-8"), digest_size=8).digest()
            bslot = int.from_bytes(hb[:4], "little") % EMBEDDING_DIM
            vec[bslot] += 0.5
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec /= norm
    return vec


def _embed_openai(text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
    import httpx

    api_key = os.environ["OPENAI_API_KEY"]
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "text-embedding-3-small",
                "input": text,
                "dimensions": EMBEDDING_DIM,  # truncate to match nomic-embed-text dim
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return np.array(resp.json()["data"][0]["embedding"], dtype=np.float32)
    except Exception as e:
        raise RuntimeError(f"OpenAI embedding failed: {e}") from e


def cosine_similarity(
    a: np.ndarray[Any, np.dtype[np.float32]],
    b: np.ndarray[Any, np.dtype[np.float32]],
) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 for zero vectors."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
