"""Tests for personal prior eligibility, budget, and relevance order."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from turnzero import retrieval
from turnzero.blocks import Block
from turnzero.embed import embed
from turnzero.formatters import block_fmt
from turnzero.mcp_server import _list_suggested_blocks
from turnzero.repositories import index_repo
from turnzero.repositories.index_repo import IndexEntry
from turnzero.retrieval import MAX_PERSONAL_TOKENS, get_identity_context
from turnzero.session import _get_project_hash

BIG = 2000  # words; a prior with this many is about 2,500 tokens


def _prior(
    slug: str,
    domain: str = "global",
    *,
    project_hash: str | None = None,
    words: int = 10,
    context_weight: int = 100,
    constraints: list[str] | None = None,
) -> Block:
    return Block(
        slug=slug,
        hash="h",
        version="1.0.0",
        domain=domain,
        intent="build",
        last_verified="2026-05-01",
        tags=[],
        context_weight=context_weight,
        constraints=[" ".join(["rule"] * words)] if constraints is None else constraints,
        anti_patterns=[],
        doc_anchors=[],
        tier="personal",
        project_hash=project_hash,
    )


def _slugs(result: tuple[list[tuple[Block, float]], int]) -> list[str]:
    return [b.slug for b, _ in result[0]]


def _library(*priors: Block) -> dict[str, Block]:
    return {p.slug: p for p in priors}


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def test_unpinned_global_prior_loads_everywhere(tmp_path: Path) -> None:
    blocks = _library(_prior("style"))

    assert _slugs(get_identity_context(blocks, "hi", [])) == ["style"]
    assert _slugs(get_identity_context(blocks, "hi", [], project_root=tmp_path)) == ["style"]


def test_pinned_prior_loads_only_in_its_project(tmp_path: Path) -> None:
    home, other = tmp_path / "home", tmp_path / "other"
    home.mkdir()
    other.mkdir()
    blocks = _library(_prior("house-rule", project_hash=_get_project_hash(home)))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=home)) == ["house-rule"]
    assert _slugs(get_identity_context(blocks, "hi", [], project_root=other)) == []
    assert _slugs(get_identity_context(blocks, "hi", [])) == []


def test_python_prior_needs_a_python_project_or_prompt(tmp_path: Path) -> None:
    py_project, js_project = tmp_path / "py", tmp_path / "js"
    py_project.mkdir()
    js_project.mkdir()
    (py_project / "requirements.txt").write_text("httpx\n", encoding="utf-8")
    (js_project / "package.json").write_text("{}", encoding="utf-8")
    blocks = _library(_prior("py-style", "python"))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=py_project)) == ["py-style"]
    assert _slugs(get_identity_context(blocks, "hi", [], project_root=js_project)) == []
    assert _slugs(
        get_identity_context(blocks, "fix this Python script", [], project_root=js_project)
    ) == ["py-style"]
    assert _slugs(get_identity_context(blocks, "hi", [])) == ["py-style"]


def test_prior_for_domain_without_markers_loads_everywhere(tmp_path: Path) -> None:
    blocks = _library(_prior("api-style", "fastapi"))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=tmp_path)) == ["api-style"]


def test_unusable_project_root_counts_as_no_markers(tmp_path: Path) -> None:
    a_file = tmp_path / "notes.txt"
    a_file.write_text("x", encoding="utf-8")
    blocks = _library(_prior("py-style", "python"), _prior("style"))

    for root in (a_file, tmp_path / "missing"):
        assert _slugs(get_identity_context(blocks, "hi", [], project_root=root)) == ["style"]


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_language_prior_loads_from_a_subdirectory_of_the_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    sub = repo / "src" / "pkg"
    sub.mkdir(parents=True)
    blocks = _library(_prior("py-style", "python"))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=sub)) == ["py-style"]


def test_pinned_prior_loads_from_a_subdirectory_of_its_project(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sub = repo / "docs"
    sub.mkdir()
    blocks = _library(_prior("house-rule", project_hash=_get_project_hash(repo)))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=sub)) == ["house-rule"]


def test_language_prior_loads_for_a_marker_one_level_down(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "backend").mkdir()
    (repo / "backend" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    blocks = _library(_prior("py-style", "python"))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=repo)) == ["py-style"]


def test_python_prior_loads_in_a_folder_with_only_py_files(tmp_path: Path) -> None:
    (tmp_path / "script.py").write_text("print(1)\n", encoding="utf-8")
    blocks = _library(_prior("py-style", "python"))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=tmp_path)) == ["py-style"]


def test_marker_search_does_not_climb_outside_a_repository(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    inner = tmp_path / "unrelated" / "notes"
    inner.mkdir(parents=True)
    blocks = _library(_prior("py-style", "python"))

    assert _slugs(get_identity_context(blocks, "hi", [], project_root=inner)) == []


def test_excluded_ids_are_not_returned() -> None:
    blocks = _library(_prior("a"), _prior("b"))

    assert _slugs(get_identity_context(blocks, "hi", [], exclude_ids={"a"})) == ["b"]


# ---------------------------------------------------------------------------
# Budget and order
# ---------------------------------------------------------------------------


def test_budget_counts_injected_text_not_declared_weight() -> None:
    blocks = _library(_prior("small-text", context_weight=99_999))

    kept, omitted = get_identity_context(blocks, "hi", [])

    assert [b.slug for b, _ in kept] == ["small-text"]
    assert omitted == 0


def test_under_budget_relevance_is_not_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(prompt: str, block: Block) -> float:
        raise AssertionError("relevance must not be computed under budget")

    monkeypatch.setattr(retrieval, "_similarity_override", explode)
    blocks = _library(_prior("b"), _prior("a"))

    assert _slugs(get_identity_context(blocks, "hi", [])) == ["a", "b"]


def test_over_budget_drops_the_least_relevant(monkeypatch: pytest.MonkeyPatch) -> None:
    scores = {"a": 0.1, "b": 0.9, "c": 0.5}
    monkeypatch.setattr(retrieval, "_similarity_override", lambda prompt, block: scores[block.slug])
    blocks = _library(_prior("a", words=BIG), _prior("b", words=BIG), _prior("c", words=BIG))
    assert sum(block_fmt.injection_tokens(b) for b in blocks.values()) > MAX_PERSONAL_TOKENS

    kept, omitted = get_identity_context(blocks, "deploy", [])

    assert [b.slug for b, _ in kept] == ["b", "c"]
    assert omitted == 1


def test_over_budget_skips_a_prior_that_does_not_fit_and_keeps_filling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One large prior must not push out smaller, less relevant ones that still fit."""
    scores = {"first": 0.9, "huge": 0.8, "small": 0.1}
    monkeypatch.setattr(retrieval, "_similarity_override", lambda prompt, block: scores[block.slug])
    blocks = _library(
        _prior("first", words=BIG), _prior("huge", words=3200), _prior("small", words=10)
    )

    kept, omitted = get_identity_context(blocks, "deploy", [])

    assert [b.slug for b, _ in kept] == ["first", "small"]
    assert omitted == 1


def test_over_budget_ties_keep_slug_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval, "_similarity_override", lambda prompt, block: 0.5)
    blocks = _library(_prior("c", words=BIG), _prior("a", words=BIG), _prior("b", words=BIG))

    kept, omitted = get_identity_context(blocks, "deploy", [])

    assert [b.slug for b, _ in kept] == ["a", "b"]
    assert omitted == 1


def test_relevance_uses_index_vectors_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieval, "_similarity_override", None)
    blocks = _library(_prior("a", words=BIG), _prior("b", words=BIG), _prior("c", words=BIG))
    index = [
        IndexEntry("a", embed("email tone and greetings"), "global", "build", []),
        IndexEntry("c", embed("deploy kubernetes cluster"), "global", "build", []),
    ]

    kept, omitted = get_identity_context(blocks, "deploy kubernetes cluster", index)

    # "c" matches the prompt; "a" has an unrelated vector and "b" has none, so
    # they tie near zero and slug order puts "a" ahead of "b".
    assert [b.slug for b, _ in kept] == ["c", "a"]
    assert omitted == 1


def test_empty_prompt_over_budget_falls_back_to_slug_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieval, "_similarity_override", None)
    blocks = _library(_prior("b", words=BIG), _prior("a", words=BIG), _prior("c", words=BIG))

    kept, omitted = get_identity_context(blocks, "", [])

    assert [b.slug for b, _ in kept] == ["a", "b"]
    assert omitted == 1


# ---------------------------------------------------------------------------
# Through the service
# ---------------------------------------------------------------------------


def _write_prior(
    data_dir: Path, tier: str, slug: str, domain: str, text: str, weight: int = 100
) -> None:
    path = data_dir / "blocks" / tier / domain / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"slug: {slug}\nversion: 1.0.0\ndomain: {domain}\nintent: build\n"
        f"last_verified: 2026-05-01\ncontext_weight: {weight}\n"
        f"constraints:\n  - \"{text}\"\nanti_patterns: []\nconfidence: 0.9\narchived: false\n",
        encoding="utf-8",
    )


# Results come back as SuggestionEntry dicts; Any keeps the helper short.
def _ids(results: list[Any]) -> list[str]:
    return [r["block_id"] for r in results]


def test_service_gates_python_prior_by_project(data_dir: Path, tmp_path: Path) -> None:
    _write_prior(data_dir, "personal", "workflow-standard", "global", "Use conventional commits")
    _write_prior(data_dir, "personal", "python-prefs", "python", "Always use mypy strict")
    py_project = tmp_path / "py"
    py_project.mkdir()
    (py_project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    elsewhere = _ids(_list_suggested_blocks("hi", project_root=tmp_path / "missing"))
    in_python = _ids(_list_suggested_blocks("hi", project_root=py_project))

    assert "workflow-standard" in elsewhere
    assert "python-prefs" not in elsewhere
    assert {"workflow-standard", "python-prefs"} <= set(in_python)


def test_service_warns_with_count_when_over_budget(data_dir: Path) -> None:
    filler = " ".join(["rule"] * BIG)
    for slug in ("a", "b", "c"):
        _write_prior(data_dir, "personal", slug, "global", filler)

    results = _list_suggested_blocks("hi")

    warning = next(r for r in results if r["block_id"] == "personal-priors-limit-warning")
    assert "6000 tokens" in warning["preview"]
    assert "1 prior(s) omitted" in warning["preview"]
    assert len([r for r in results if r["score"] == 2.0]) == 2


def test_expert_results_do_not_depend_on_personal_size(data_dir: Path) -> None:
    """Personal priors used to be subtracted from the expert budget."""
    _write_prior(
        data_dir,
        "community",
        "fastapi-async-build-x",
        "fastapi",
        "Use async def for FastAPI route handlers",
        weight=3000,
    )
    _write_prior(data_dir, "personal", "p1", "global", "Use conventional commits", weight=1200)
    _write_prior(data_dir, "personal", "p2", "global", "Keep answers short", weight=1200)
    index_repo.build(data_dir / "blocks", data_dir / "index.jsonl", data_dir=data_dir)

    results = _list_suggested_blocks("build a FastAPI async REST API")

    assert "fastapi-async-build-x" in _ids(results)


def test_personal_priors_never_come_back_through_the_expert_query(
    data_dir: Path, tmp_path: Path
) -> None:
    """A pinned or gated personal prior must not return as an expert match."""
    home, other = tmp_path / "home", tmp_path / "other"
    home.mkdir()
    other.mkdir()
    text = "Use async def for FastAPI route handlers"
    _write_prior(data_dir, "personal", "fastapi-house-rule", "fastapi", text)
    pinned = data_dir / "blocks" / "personal" / "fastapi" / "fastapi-house-rule.yaml"
    pinned.write_text(
        pinned.read_text(encoding="utf-8") + f"project_hash: {_get_project_hash(home)}\n",
        encoding="utf-8",
    )
    _write_prior(data_dir, "personal", "fastapi-python-habit", "python", text)
    index_repo.build(data_dir / "blocks", data_dir / "index.jsonl", data_dir=data_dir)
    prompt = "build a FastAPI async REST API"

    at_home = _ids(_list_suggested_blocks(prompt, project_root=home))
    elsewhere = _ids(_list_suggested_blocks(prompt, project_root=other))

    assert "fastapi-house-rule" in at_home
    assert "fastapi-house-rule" not in elsewhere
    assert "fastapi-python-habit" not in elsewhere
