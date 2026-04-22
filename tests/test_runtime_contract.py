"""Runtime compatibility contract for the packaging/runtime surface.

These checks prevent environment drift between docs/tests and packaging:
- Python range matches what we actively test in CI and local workflows.
"""

from __future__ import annotations

from pathlib import Path


def _pyproject_text() -> str:
    root = Path(__file__).parent.parent
    return (root / "pyproject.toml").read_text(encoding="utf-8")


def test_requires_python_is_bounded_for_embedding_stack() -> None:
    text = _pyproject_text()
    assert 'requires-python = ">=3.12,<3.14"' in text


def test_embedding_dependency_contract_is_pinned() -> None:
    text = _pyproject_text()
    assert '"numpy>=1.26,<2"' in text
    assert "sentence-transformers" not in text
    assert "transformers" not in text
