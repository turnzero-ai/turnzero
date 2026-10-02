"""Tests for turnzero.harvest — YAML parsing, normalisation, and file writing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from turnzero.harvest import (
    _normalise,
    content_hash,
    load_conversation,
    parse_candidates,
    write_candidate,
)

# ---------------------------------------------------------------------------
# load_conversation
# ---------------------------------------------------------------------------


def test_load_txt(tmp_path: Path) -> None:
    f = tmp_path / "conv.txt"
    f.write_text("User: hi\nAssistant: hello", encoding="utf-8")
    assert load_conversation(f) == "User: hi\nAssistant: hello"


def test_load_md(tmp_path: Path) -> None:
    f = tmp_path / "conv.md"
    f.write_text("# Chat\n**User:** help\n**AI:** sure", encoding="utf-8")
    text = load_conversation(f)
    assert "# Chat" in text


def test_load_json_list(tmp_path: Path) -> None:
    data = [
        {"role": "user", "content": "How do I use FastAPI?"},
        {"role": "assistant", "content": "Use async def for route handlers."},
    ]
    f = tmp_path / "conv.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    result = load_conversation(f)
    assert "User: How do I use FastAPI?" in result
    assert "Assistant: Use async def" in result


def test_load_json_messages_key(tmp_path: Path) -> None:
    data = {"messages": [{"role": "user", "content": "hello"}]}
    f = tmp_path / "conv.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    result = load_conversation(f)
    assert "User: hello" in result


def test_load_json_invalid_falls_back_to_raw(tmp_path: Path) -> None:
    f = tmp_path / "conv.json"
    f.write_text("not valid json {{{", encoding="utf-8")
    result = load_conversation(f)
    assert "not valid json" in result


# ---------------------------------------------------------------------------
# parse_candidates
# ---------------------------------------------------------------------------

MINIMAL_YAML = """\
- id: fastapi-debug-harvested
  version: "1.0.0"
  stack: fastapi
  intent: debug
  last_verified: "2026-04-11"
  tags: [fastapi, python]
  token_budget: 200
  conflicts_with: []
  requires: []
  constraints:
    - "Use async def for route handlers"
  anti_patterns:
    - "Do not use sync def for IO-bound routes"
  doc_anchors: []
"""


def test_parse_minimal_yaml() -> None:
    candidates = parse_candidates(MINIMAL_YAML)
    assert len(candidates) == 1
    assert candidates[0]["id"] == "fastapi-debug-harvested"
    assert candidates[0]["stack"] == "fastapi"
    assert candidates[0]["intent"] == "debug"


def test_parse_strips_markdown_fences() -> None:
    fenced = f"```yaml\n{MINIMAL_YAML}```"
    candidates = parse_candidates(fenced)
    assert len(candidates) == 1
    assert candidates[0]["id"] == "fastapi-debug-harvested"


def test_parse_single_dict_becomes_list() -> None:
    single = """\
id: nextjs-build-harvested
stack: nextjs
intent: build
constraints:
  - "Use App Router"
"""
    candidates = parse_candidates(single)
    assert len(candidates) == 1


def test_parse_multiple_blocks() -> None:
    multi = """\
- id: block-one-build
  stack: nextjs
  intent: build
  constraints: ["Use App Router"]
  anti_patterns: ["Do not use Pages Router"]
  doc_anchors: []

- id: block-two-debug
  stack: fastapi
  intent: debug
  constraints: ["Check async def"]
  anti_patterns: ["Do not use sync def"]
  doc_anchors: []
"""
    candidates = parse_candidates(multi)
    assert len(candidates) == 2


def test_parse_invalid_yaml_raises() -> None:
    with pytest.raises(ValueError, match="Could not parse|No YAML found"):
        parse_candidates("this is not yaml: [[[")


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------


def test_normalise_fills_defaults() -> None:
    raw: dict[str, Any] = {"id": "test-build", "stack": "python", "intent": "build"}
    result = _normalise(raw)
    assert result["version"] == "1.0.0"
    assert result["conflicts_with"] == []
    assert result["requires"] == []
    assert result["constraints"] == []
    assert result["anti_patterns"] == []
    assert result["doc_anchors"] == []
    assert result["context_weight"] == 50  # min value when no content


def test_normalise_invalid_intent_defaults_to_build() -> None:
    raw: dict[str, Any] = {"id": "x", "stack": "python", "intent": "nonsense"}
    result = _normalise(raw)
    assert result["intent"] == "build"


def test_normalise_generates_id_when_missing() -> None:
    raw: dict[str, Any] = {"stack": "rust", "intent": "migrate"}
    result = _normalise(raw)
    assert result["id"] == "rust-migrate-extracted"


def test_normalise_generates_id_when_placeholder() -> None:
    raw: dict[str, Any] = {
        "id": "<descriptive-slug>-<intent>",
        "stack": "go",
        "intent": "review",
    }
    result = _normalise(raw)
    assert result["id"] == "go-review-extracted"


def test_normalise_preserves_existing_values() -> None:
    raw: dict[str, Any] = {
        "id": "custom-id",
        "stack": "rust",
        "intent": "debug",
        "version": "2.0.0",
        "token_budget": 800,
    }
    result = _normalise(raw)
    assert result["id"] == "custom-id"
    assert result["version"] == "2.0.0"
    assert result["token_budget"] == 800


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


def test_content_hash_is_16_hex_chars() -> None:
    candidate = {
        "id": "test",
        "stack": "python",
        "intent": "build",
        "constraints": ["use async"],
    }
    h = content_hash(candidate)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_content_hash_excludes_id() -> None:
    c1 = {"id": "id-one", "stack": "python", "constraints": ["use async"]}
    c2 = {"id": "id-two", "stack": "python", "constraints": ["use async"]}
    assert content_hash(c1) == content_hash(c2)


def test_content_hash_changes_with_content() -> None:
    c1 = {"id": "x", "stack": "python", "constraints": ["use async"]}
    c2 = {"id": "x", "stack": "python", "constraints": ["use sync"]}
    assert content_hash(c1) != content_hash(c2)


# ---------------------------------------------------------------------------
# write_candidate
# ---------------------------------------------------------------------------


def test_write_candidate_creates_file(tmp_path: Path) -> None:
    candidate = {
        "id": "test-block-build",
        "stack": "python",
        "intent": "build",
        "version": "1.0.0",
        "constraints": ["Use async def"],
        "anti_patterns": ["Do not use sync def"],
        "doc_anchors": [],
    }
    out_path = write_candidate(candidate, tmp_path)
    assert out_path == tmp_path / "test-block-build.yaml"
    assert out_path.exists()


def test_write_candidate_round_trips(tmp_path: Path) -> None:
    candidate = {
        "id": "roundtrip-build",
        "stack": "typescript",
        "intent": "build",
        "version": "1.0.0",
        "tags": ["ts", "strict"],
        "constraints": ["Enable strict mode"],
        "anti_patterns": ["Do not use any"],
        "doc_anchors": [],
        "conflicts_with": [],
        "requires": [],
        "token_budget": 300,
        "last_verified": "2026-04-11",
    }
    out_path = write_candidate(candidate, tmp_path)
    loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert loaded["id"] == "roundtrip-build"
    assert loaded["constraints"] == ["Enable strict mode"]
    assert loaded["tags"] == ["ts", "strict"]


# ---------------------------------------------------------------------------
# parse_claude_session
# ---------------------------------------------------------------------------


def test_parse_claude_session_keeps_typed_turns(tmp_path: Path) -> None:
    from tests.fixtures.transcripts import assistant, user, write_transcript
    from turnzero.harvest import parse_claude_session

    path = write_transcript(
        tmp_path,
        "s",
        [user("set up the project", 0), assistant("Done.", 1), user("now add tests", 2)],
    )
    parsed = parse_claude_session(path)

    assert [(t.line, t.text, t.after_assistant) for t in parsed.user_turns] == [
        (0, "set up the project", False),
        (2, "now add tests", True),
    ]
    assert parsed.cwd == "/work/proj"
    assert parsed.lines == 3
    assert parsed.last_ts == parsed.user_turns[1].ts > parsed.user_turns[0].ts


def test_parse_claude_session_drops_synthetic_user_entries(tmp_path: Path) -> None:
    from tests.fixtures.transcripts import (
        assistant,
        tool_result,
        user,
        write_transcript,
    )
    from turnzero.harvest import parse_claude_session

    path = write_transcript(
        tmp_path,
        "s",
        [
            assistant("Hi.", 0),
            tool_result("t0", ["some-block"], 1),
            user("expanded skill text", 2, isMeta=True),
            user("subagent prompt", 3, isSidechain=True),
            user("summary of earlier turns", 4, isCompactSummary=True),
            user("background task finished", 5, origin={"kind": "task-notification"}),
            user("<command-name>/clear</command-name>", 6),
            user("[Request interrupted by user]", 7),
            user("the only typed turn", 8),
        ],
    )
    parsed = parse_claude_session(path)

    assert [t.text for t in parsed.user_turns] == ["the only typed turn"]


def test_parse_claude_session_extracts_injections(tmp_path: Path) -> None:
    from tests.fixtures.transcripts import (
        assistant,
        inject_call,
        suggest_call,
        tool_result,
        user,
        write_transcript,
    )
    from turnzero.harvest import parse_claude_session

    path = write_transcript(
        tmp_path,
        "s",
        [
            user("build it", 0),
            assistant("Looking.", 1, tool_uses=[suggest_call("t1")]),
            tool_result("t1", ["block-a", "personal-priors-limit-warning"], 2),
            assistant("More.", 3, tool_uses=[suggest_call("t2", inject_all=False)]),
            tool_result("t2", ["block-preview-only"], 4, full_text=False),
            assistant("Reading.", 5, tool_uses=[inject_call("block-b")]),
        ],
    )
    parsed = parse_claude_session(path)

    assert [(i.line, i.block_ids) for i in parsed.injections] == [
        (2, ("block-a",)),
        (5, ("block-b",)),
    ]


def test_parse_claude_session_counts_full_text_without_inject_all(
    tmp_path: Path,
) -> None:
    """Since full text became the default, calls no longer pass inject_all."""
    from tests.fixtures.transcripts import (
        assistant,
        suggest_call,
        tool_result,
        user,
        write_transcript,
    )
    from turnzero.harvest import parse_claude_session

    path = write_transcript(
        tmp_path,
        "s",
        [
            user("build it", 0),
            assistant("Looking.", 1, tool_uses=[suggest_call("t1", inject_all=False)]),
            tool_result("t1", ["block-a"], 2),
        ],
    )
    parsed = parse_claude_session(path)

    assert [(i.line, i.block_ids) for i in parsed.injections] == [(2, ("block-a",))]


def test_parse_claude_session_skips_malformed_line(tmp_path: Path) -> None:
    from tests.fixtures.transcripts import assistant, user, write_transcript
    from turnzero.harvest import parse_claude_session

    path = write_transcript(tmp_path, "s", [user("first", 0), assistant("ok", 1)])
    text = path.read_text(encoding="utf-8")
    path.write_text(text + "{not json\n" + json.dumps(user("second", 2)) + "\n")
    parsed = parse_claude_session(path)

    assert [t.text for t in parsed.user_turns] == ["first", "second"]
    assert parsed.lines == 4


def test_parse_claude_session_does_not_count_half_written_last_line(
    tmp_path: Path,
) -> None:
    from tests.fixtures.transcripts import assistant, user, write_transcript
    from turnzero.harvest import parse_claude_session

    path = write_transcript(tmp_path, "s", [user("first", 0), assistant("ok", 1)])
    half = json.dumps(user("still being written", 2))[:25]
    path.write_text(path.read_text(encoding="utf-8") + half)
    parsed = parse_claude_session(path)

    assert parsed.lines == 2
    assert [t.text for t in parsed.user_turns] == ["first"]


def test_parse_claude_session_handles_entries_without_origin(tmp_path: Path) -> None:
    from tests.fixtures.transcripts import assistant, user, write_transcript
    from turnzero.harvest import parse_claude_session

    old_style = user("typed in an older client", 1)
    del old_style["origin"]
    path = write_transcript(tmp_path, "s", [assistant("Hi.", 0), old_style])
    parsed = parse_claude_session(path)

    assert [t.text for t in parsed.user_turns] == ["typed in an older client"]


def test_parse_claude_session_keeps_text_next_to_image(tmp_path: Path) -> None:
    from tests.fixtures.transcripts import assistant, user, write_transcript
    from turnzero.harvest import parse_claude_session

    with_image = user("ignored", 1)
    with_image["message"]["content"] = [
        {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
        {"type": "text", "text": "<system-reminder>injected</system-reminder>"},
        {"type": "text", "text": "the layout is off, see screenshot"},
    ]
    path = write_transcript(tmp_path, "s", [assistant("Hi.", 0), with_image])
    parsed = parse_claude_session(path)

    assert [t.text for t in parsed.user_turns] == ["the layout is off, see screenshot"]
