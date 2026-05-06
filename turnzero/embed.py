"""Embedding with backend fallback and cosine similarity."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

# Dimension produced by nomic-embed-text. All backends normalise to this.
EMBEDDING_DIM = 768
HTTP_OK = 200

_ONNX_MODEL_REPO = "nomic-ai/nomic-embed-text-v1.5"
# (remote_path, local_relative_path) pairs
_ONNX_MODEL_FILES: list[tuple[str, str]] = [
    ("onnx/model.onnx", "onnx/model.onnx"),
    ("tokenizer.json", "tokenizer.json"),
]

# Mutable cache dict avoids module-level global reassignment (PLW0603).
# Values are Any because onnxruntime/tokenizers are optional deps.
_onnx_cache: dict[str, Any] = {}  # keys: "session", "tokenizer"


def get_model_id() -> str:
    """Return the ID of the current active embedding model."""
    if os.environ.get("TURNZERO_TEST_EMBEDDINGS") == "1":
        return "test-hash-blake2b-768"
    if _is_onnx_available() and _is_onnx_model_downloaded():
        return "onnx:nomic-embed-text-v1.5"
    if os.environ.get("OPENAI_API_KEY") and not _is_ollama_running():
        return "openai:text-embedding-3-small"
    return "ollama:nomic-embed-text"


def _is_onnx_available() -> bool:
    """Return True if onnxruntime and tokenizers are importable."""
    try:
        import onnxruntime  # noqa: F401
        from tokenizers import Tokenizer  # noqa: F401

        return True
    except ImportError:
        return False


def _get_onnx_model_dir() -> Path:
    base = Path(os.environ.get("TURNZERO_DATA_DIR", str(Path.home() / ".turnzero")))
    return base / "models" / "nomic-embed-text-v1.5"


def _is_onnx_model_downloaded() -> bool:
    model_dir = _get_onnx_model_dir()
    return (model_dir / "onnx" / "model.onnx").exists() and (
        model_dir / "tokenizer.json"
    ).exists()


def download_onnx_model(model_dir: Path | None = None) -> None:
    """Download nomic-embed-text-v1.5 ONNX model files.

    Args:
        model_dir: Target directory. Defaults to ~/.turnzero/models/nomic-embed-text-v1.5.
    """
    import httpx
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        SpinnerColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )

    target = model_dir or _get_onnx_model_dir()
    base_url = f"https://huggingface.co/{_ONNX_MODEL_REPO}/resolve/main"

    for remote_path, local_rel in _ONNX_MODEL_FILES:
        local_path = target / local_rel
        if local_path.exists():
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{base_url}/{remote_path}"
        filename = Path(remote_path).name

        with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or None
            with Progress(
                SpinnerColumn(),
                f"[cyan]{filename}[/cyan]",
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task(filename, total=total)
                with local_path.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                        progress.update(task, advance=len(chunk))


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
      1. ONNX nomic-embed-text-v1.5  (in-process, no daemon — pip install turnzero[local])
      2. ollama nomic-embed-text      (local server)
      3. OpenAI text-embedding-3-small (cloud, OPENAI_API_KEY)

    Everything runs locally by default. No text leaves the machine unless
    OPENAI_API_KEY is explicitly set.
    """
    if os.environ.get("TURNZERO_TEST_EMBEDDINGS") == "1":
        return _embed_test(text)

    if _is_onnx_available() and _is_onnx_model_downloaded():
        try:
            return _embed_onnx(text)
        except RuntimeError:
            pass

    try:
        return _embed_ollama(text)
    except RuntimeError:
        pass

    if os.environ.get("OPENAI_API_KEY"):
        return _embed_openai(text)

    raise RuntimeError(
        "No embedding backend available.\n\n"
        "Install local ONNX backend (recommended, no daemon):\n"
        "  pip install 'turnzero[local]'\n"
        "  turnzero setup\n\n"
        "Or start ollama:\n"
        "  ollama serve && ollama pull nomic-embed-text\n\n"
        "Or use OpenAI:\n"
        "  export OPENAI_API_KEY=sk-..."
    )


def _embed_onnx(text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise RuntimeError(
            f"ONNX deps not installed: {exc}. Run: pip install 'turnzero[local]'"
        ) from exc

    model_dir = _get_onnx_model_dir()

    if "tokenizer" not in _onnx_cache:
        tok: Any = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        tok.enable_padding(length=512)
        tok.enable_truncation(max_length=512)
        _onnx_cache["tokenizer"] = tok

    if "session" not in _onnx_cache:
        _onnx_cache["session"] = ort.InferenceSession(
            str(model_dir / "onnx" / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )

    tokenizer = _onnx_cache["tokenizer"]
    session = _onnx_cache["session"]

    encoding = tokenizer.encode(text)
    input_ids = np.array([encoding.ids], dtype=np.int64)
    attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

    # Some ONNX exports omit token_type_ids; check dynamically.
    input_names = {inp.name for inp in session.get_inputs()}
    feeds: dict[str, np.ndarray[Any, Any]] = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    }
    if "token_type_ids" in input_names:
        feeds["token_type_ids"] = np.zeros_like(input_ids)

    try:
        outputs = session.run(None, feeds)
    except Exception as exc:
        raise RuntimeError(f"ONNX inference failed: {exc}") from exc

    # Mean-pool last hidden state over sequence dimension, weighted by attention mask.
    token_embeddings = outputs[0].astype(np.float32)  # (1, seq_len, 768)
    mask = attention_mask[..., np.newaxis].astype(np.float32)  # (1, seq_len, 1)
    pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
    vec: np.ndarray[Any, np.dtype[np.float32]] = pooled[0]
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec = vec / norm
    return vec


def _ollama_timeout() -> float:
    """Return Ollama embedding timeout in seconds.

    Ollama cold-starts (model not in RAM) can take 15-60s on slow hardware.
    Default 30s covers most cases. Override with TURNZERO_OLLAMA_TIMEOUT_SECONDS.
    """
    raw = os.environ.get("TURNZERO_OLLAMA_TIMEOUT_SECONDS", "30")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 30.0


def _embed_ollama(text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not host.startswith("http"):
        host = f"http://{host}"

    try:
        resp = httpx.post(
            f"{host}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=_ollama_timeout(),
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
