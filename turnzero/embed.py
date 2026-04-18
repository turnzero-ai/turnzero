"""Embedding with multiple backend fallbacks and cosine similarity."""

from __future__ import annotations

import os

import numpy as np

# Dimension produced by nomic-embed-text. All backends are normalised to this.
EMBEDDING_DIM = 768

# sentence-transformers model — same weights as ollama's nomic-embed-text
_ST_MODEL_NAME = "nomic-ai/nomic-embed-text-v1"
_st_model = None  # lazy singleton


def embed(text: str) -> np.ndarray:
    """Embed text, returning a float32 ndarray of shape (768,).

    Fallback chain:
      1. ollama nomic-embed-text       (local, no download if already pulled)
      2. sentence-transformers         (local, pip install turnzero[local])
      3. OpenAI text-embedding-3-small (cloud, OPENAI_API_KEY)

    Raises RuntimeError with actionable instructions if nothing is available.
    """
    try:
        return _embed_ollama(text)
    except RuntimeError:
        pass

    try:
        return _embed_sentence_transformers(text)
    except RuntimeError:
        pass

    if os.environ.get("OPENAI_API_KEY"):
        return _embed_openai(text)

    raise RuntimeError(
        "No embedding backend available.\n\n"
        "Option 1 (local, no server):\n"
        "  pip install 'turnzero[local]'\n\n"
        "Option 2 (local, with server):\n"
        "  ollama serve && ollama pull nomic-embed-text\n\n"
        "Option 3 (cloud):\n"
        "  export OPENAI_API_KEY=sk-..."
    )


def _embed_ollama(text: str) -> np.ndarray:
    try:
        import ollama
    except ImportError as e:
        raise RuntimeError("ollama package not installed") from e

    try:
        result = ollama.embeddings(model="nomic-embed-text", prompt=text)
        return np.array(result["embedding"], dtype=np.float32)
    except Exception as e:
        raise RuntimeError(f"ollama unavailable: {e}") from e


def _embed_sentence_transformers(text: str) -> np.ndarray:
    global _st_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError("sentence-transformers not installed") from e
    try:
        if _st_model is None:
            _st_model = SentenceTransformer(_ST_MODEL_NAME, trust_remote_code=True)
        vec = _st_model.encode(text, normalize_embeddings=True)
        return np.array(vec, dtype=np.float32)
    except Exception as e:
        raise RuntimeError(f"sentence-transformers failed: {e}") from e


def _embed_openai(text: str) -> np.ndarray:
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("httpx not installed") from e

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


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 for zero vectors."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
