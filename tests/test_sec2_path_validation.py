"""Tests for SEC-2 path traversal and identifier validation."""

from __future__ import annotations

import pytest
from pathlib import Path
from turnzero.mcp_server import learn_from_session, submit_candidate

from turnzero.validators import (
    safe_path,
    validate_domain,
    validate_session_name,
    validate_slug,
)


def test_validate_slug_valid() -> None:
    validate_slug("valid-slug-123")
    validate_slug("another_valid.slug")


def test_validate_slug_invalid_chars() -> None:
    with pytest.raises(ValueError, match="Invalid slug"):
        validate_slug("Invalid Slug")
    with pytest.raises(ValueError, match="Invalid slug"):
        validate_slug("slug$")


def test_validate_slug_too_short() -> None:
    with pytest.raises(ValueError, match="Invalid slug"):
        validate_slug("ab")


def test_validate_slug_too_long() -> None:
    with pytest.raises(ValueError, match="Invalid slug"):
        validate_slug("a" * 129)


def test_validate_slug_traversal() -> None:
    with pytest.raises(ValueError):
        validate_slug("../hidden")
    with pytest.raises(ValueError):
        validate_slug("sub/dir")


def test_validate_domain_valid() -> None:
    validate_domain("python")
    validate_domain("fastapi-123")


def test_validate_domain_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid domain"):
        validate_domain("My Domain")
    with pytest.raises(ValueError, match="Invalid domain"):
        validate_domain("domain.dot")


def test_validate_session_name_valid() -> None:
    validate_session_name("my-session")


def test_validate_session_name_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid session name"):
        validate_session_name("session/traversal")


def test_safe_path_valid(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    path = safe_path(base, "sub", "file.txt")
    # Note: path.resolve() might have different case on some OS, but should be under base
    assert str(path).startswith(str(base.resolve()))


def test_safe_path_traversal(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(ValueError, match="escapes base directory"):
        safe_path(base, "..", "outside.txt")


def test_submit_candidate_validates_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="Invalid slug"):
        submit_candidate(
            block_id="sh",  # too short
            domain="python",
            intent="build",
            constraints=["Do X"],
            anti_patterns=[],
        )
    with pytest.raises(ValueError, match="Invalid domain"):
        submit_candidate(
            block_id="valid-slug",
            domain="invalid domain",
            intent="build",
            constraints=["Do X"],
            anti_patterns=[],
        )


def test_learn_from_session_validates_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="Invalid session name"):
        learn_from_session(transcript="hello", session_name="../traversal")

