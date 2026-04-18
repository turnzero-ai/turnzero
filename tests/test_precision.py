"""Hit Rate@K evaluation harness for TurnZero retrieval.

Ground truth is in tests/validation_set.json.
Each entry: {"prompt": "...", "relevant_block_ids": ["id1", ...]}

Metric: Hit Rate@K — fraction of queries where at least one relevant block
appears in the top-K results. With 1 relevant block per query this equals the
fraction of queries where the correct block is retrieved.

Target: Hit Rate@3 >= 0.70 (i.e. ≥7/10 queries return the correct block)

Note on Precision@K: with 1 relevant block per query, standard Precision@K
caps at 1/K (= 0.33 for K=3). Hit Rate@K is the meaningful metric here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from turnzero.blocks import load_all_blocks
from turnzero.retrieval import load_index
from turnzero.retrieval import query as _query

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
BLOCKS_DIR = DATA_DIR / "blocks"
INDEX_PATH = DATA_DIR / "index.jsonl"
VALIDATION_PATH = Path(__file__).parent / "validation_set.json"

TOP_K = 3
THRESHOLD = 0.75
TARGET_HIT_RATE = 0.70


@pytest.fixture(scope="module")
def retrieval_fixtures():  # type: ignore[return]
    """Load blocks and index once for all precision tests."""
    if not INDEX_PATH.exists():
        pytest.skip("Index not built — run: turnzero index build")
    blocks = load_all_blocks(BLOCKS_DIR)
    index = load_index(INDEX_PATH)
    return blocks, index


@pytest.fixture(scope="module")
def validation_set() -> list[dict]:
    if not VALIDATION_PATH.exists():
        pytest.skip(f"Validation set not found: {VALIDATION_PATH}")
    with VALIDATION_PATH.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hit_at_k(retrieved: list[str], relevant: set[str], k: int) -> bool:
    """True if at least one of the top-k retrieved IDs is in the relevant set."""
    return any(r in relevant for r in retrieved[:k])


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of top-k retrieved IDs that are in the relevant set."""
    top = retrieved[:k]
    return sum(1 for r in top if r in relevant) / k if k > 0 else 0.0


# ---------------------------------------------------------------------------
# Per-query parametrised tests
# ---------------------------------------------------------------------------

def _load_cases() -> list[tuple[str, str, list[str]]]:
    """Return (prompt, first_relevant_id, all_relevant_ids) tuples for parametrize."""
    if not VALIDATION_PATH.exists():
        return []
    with VALIDATION_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return [(e["prompt"], e["relevant_block_ids"][0], e["relevant_block_ids"]) for e in data]


@pytest.mark.parametrize("prompt,expected_top,all_relevant", _load_cases())
def test_top1_retrieval(
    prompt: str,
    expected_top: str,
    all_relevant: list[str],
    retrieval_fixtures,  # type: ignore[no-untyped-def]
) -> None:
    """Expected top block appears in top-K results."""
    blocks, index = retrieval_fixtures
    results = _query(prompt, index, blocks, top_k=TOP_K, threshold=THRESHOLD, context_weight=4000, strict_intent=True)
    retrieved_ids = [block.id for block, _ in results]

    assert retrieved_ids, (
        f"No results for prompt: {prompt!r}\n"
        f"Expected: {expected_top}\n"
        f"Check that the index is built and threshold ({THRESHOLD}) is appropriate."
    )
    assert expected_top in retrieved_ids, (
        f"Expected block '{expected_top}' not in top-{TOP_K} results.\n"
        f"Got: {retrieved_ids}\n"
        f"Prompt: {prompt!r}"
    )


# ---------------------------------------------------------------------------
# Aggregate Hit Rate@K test (must meet 0.70 target)
# ---------------------------------------------------------------------------

def test_hit_rate_at_k(retrieval_fixtures, validation_set) -> None:  # type: ignore[no-untyped-def]
    """Hit Rate@3 across all validation queries must be >= 0.70.

    Hit Rate@K = fraction of queries where at least one relevant block
    appears in the top-K results. With 1 relevant block per query this
    equals the fraction of queries where the correct block is retrieved.
    """
    blocks, index = retrieval_fixtures
    hits: list[bool] = []

    for entry in validation_set:
        prompt = entry["prompt"]
        relevant = set(entry["relevant_block_ids"])
        results = _query(prompt, index, blocks, top_k=TOP_K, threshold=THRESHOLD, context_weight=4000)
        retrieved_ids = [block.id for block, _ in results]
        hits.append(hit_at_k(retrieved_ids, relevant, TOP_K))

    hit_rate = sum(hits) / len(hits) if hits else 0.0

    assert hit_rate >= TARGET_HIT_RATE, (
        f"Hit Rate@{TOP_K} = {hit_rate:.3f} is below target {TARGET_HIT_RATE:.2f}\n"
        f"Per-query hits: {[int(h) for h in hits]}"
    )


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

def test_hit_at_k_true() -> None:
    assert hit_at_k(["a", "b", "c"], {"a"}, 3) is True


def test_hit_at_k_false() -> None:
    assert hit_at_k(["x", "y", "z"], {"a"}, 3) is False


def test_hit_at_k_only_top_k() -> None:
    assert hit_at_k(["x", "x", "x", "a"], {"a"}, 3) is False


def test_precision_at_k_perfect() -> None:
    assert precision_at_k(["a", "b", "c"], {"a", "b", "c"}, 3) == pytest.approx(1.0)


def test_precision_at_k_zero() -> None:
    assert precision_at_k(["x", "y", "z"], {"a", "b"}, 3) == pytest.approx(0.0)


def test_precision_at_k_partial() -> None:
    assert precision_at_k(["a", "x", "b"], {"a", "b"}, 3) == pytest.approx(2 / 3)


def test_precision_at_k_only_top_k_counted() -> None:
    assert precision_at_k(["x", "x", "x", "a"], {"a"}, 3) == pytest.approx(0.0)


def test_precision_at_k_zero_k() -> None:
    assert precision_at_k(["a"], {"a"}, 0) == pytest.approx(0.0)
