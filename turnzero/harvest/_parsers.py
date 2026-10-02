"""Conversation file format parsers — load any supported format to plain text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from turnzero.types import BLOCK_ID_SENTINELS, TOOL_INJECT_BLOCK, TOOL_LIST_SUGGESTED

MIN_TURN_WORDS = 3
MIN_SESSION_WORDS = 5

_TURNZERO_TOOL_MARK = "turnzero"
# Text Claude Code writes into "user" entries that the user never typed.
_SYNTHETIC_PREFIXES = ("<", "[Request interrupted")


@dataclass(frozen=True)
class UserTurn:
    line: int
    ts: float
    text: str
    after_assistant: bool


@dataclass(frozen=True)
class Injection:
    line: int
    block_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedSession:
    cwd: str | None
    lines: int
    last_ts: float
    user_turns: list[UserTurn]
    injections: list[Injection]


def load_conversation(path: Path) -> str:
    """Load a conversation from any supported format and return plain text.

    Supported formats (detected automatically):
      - Claude Code session    .jsonl  — auto-discovered from ~/.claude/projects/
      - OpenAI messages JSON   .json   — [{role, content}] or {messages:[...]}
      - ChatGPT data export    .json   — conversations.json with mapping structure
      - Aider chat history     .md     — .aider.chat.history.md with #### role markers
      - Plain markdown/text    .md .txt — any User:/Assistant: patterns
    """
    if path.suffix == ".jsonl":
        return convert_claude_session(path)

    text = path.read_text(encoding="utf-8")

    if path.suffix == ".json":
        try:
            data = json.loads(text)
            result = _parse_json_conversation(data)
            if result:
                return result
        except (json.JSONDecodeError, KeyError):
            pass

    # Aider and any markdown with role headers
    if True:  # noqa: SIM210 — future: dispatch on path.suffix
        result = _parse_markdown_conversation(text)
        if result:
            return result

    return text


def _parse_json_conversation(data: Any) -> str:
    """Detect and parse JSON conversation formats. Returns empty string if unrecognised."""
    # Standard OpenAI messages format: [{role, content}, ...]
    if (
        isinstance(data, list)
        and data
        and isinstance(data[0], dict)
        and "role" in data[0]
    ):
        return _turns_from_messages(data)

    # OpenAI SDK format: {messages: [...]}
    if isinstance(data, dict) and "messages" in data:
        return _turns_from_messages(data["messages"])

    # ChatGPT data export: list of conversations, each with a mapping tree
    if (
        isinstance(data, list)
        and data
        and isinstance(data[0], dict)
        and "mapping" in data[0]
    ):
        parts: list[str] = []
        for convo in data:
            parts.append(_parse_chatgpt_mapping(convo.get("mapping", {})))
        return "\n\n---\n\n".join(p for p in parts if p)

    # Single ChatGPT conversation with mapping
    if isinstance(data, dict) and "mapping" in data:
        return _parse_chatgpt_mapping(data["mapping"])

    return ""


def _turns_from_messages(messages: Any) -> str:
    """Convert a list of {role, content} dicts to plain conversation text."""
    turns: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        if role not in ("user", "assistant", "human", "ai"):
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            # Handle OpenAI content array [{type: "text", text: "..."}]
            text = " ".join(
                str(c.get("text", ""))
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            ).strip()
        else:
            text = str(content).strip()
        if text:
            label = "User" if role in ("user", "human") else "Assistant"
            turns.append(f"{label}: {text}")
    return "\n\n".join(turns)


def _parse_chatgpt_mapping(mapping: Any) -> str:
    """Parse ChatGPT's conversation mapping tree into ordered plain text."""
    if not isinstance(mapping, dict):
        return ""

    # Build parent→children index and find root
    children: dict[str, list[str]] = {}
    root_id: str | None = None
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        parent = node.get("parent")
        if parent is None:
            root_id = node_id
        else:
            children.setdefault(parent, []).append(node_id)

    if root_id is None and mapping:
        root_id = next(iter(mapping))

    # Walk the tree depth-first, collecting user/assistant text nodes
    turns: list[str] = []

    def walk(node_id: str) -> None:
        node = mapping.get(node_id, {})
        msg = node.get("message") or {}
        author = (msg.get("author") or {}).get("role", "")
        content_obj = msg.get("content") or {}
        parts = content_obj.get("parts", [])
        text = " ".join(str(p) for p in parts if isinstance(p, str)).strip()
        if (
            author in ("user", "assistant")
            and text
            and len(text.split()) >= MIN_TURN_WORDS
        ):
            label = "User" if author == "user" else "Assistant"
            turns.append(f"{label}: {text}")
        for child_id in children.get(node_id, []):
            walk(child_id)

    if root_id:
        walk(root_id)

    return "\n\n".join(turns)


def _parse_markdown_conversation(text: str) -> str:
    """Extract conversation turns from markdown with common role markers.

    Handles:
      - Aider:    #### user / #### assistant
      - Generic:  **User:** / **Assistant:**
      - Simple:   User: / Assistant: (already plain text, returned as-is)
    """
    # Aider format: #### user\n...\n#### assistant\n...
    aider_pattern = re.compile(
        r"^#{1,4}\s+(user|assistant|human|ai)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    if aider_pattern.search(text):
        turns: list[str] = []
        chunks = aider_pattern.split(text)
        # split gives: [pre, role1, content1, role2, content2, ...]
        i = 1
        while i + 1 < len(chunks):
            role = chunks[i].strip().lower()
            content = chunks[i + 1].strip()
            if content and len(content.split()) >= MIN_TURN_WORDS:
                label = "User" if role in ("user", "human") else "Assistant"
                turns.append(f"{label}: {content}")
            i += 2
        if turns:
            return "\n\n".join(turns)

    # Bold marker format: **User:** or **Assistant:**
    bold_pattern = re.compile(r"\*\*(User|Assistant|Human|AI)\*\*:?\s*", re.IGNORECASE)
    if bold_pattern.search(text):
        return bold_pattern.sub(lambda m: m.group(1).capitalize() + ": ", text)

    return ""


def convert_claude_session(jsonl_path: Path) -> str:
    """Convert a Claude Code session JSONL file to plain conversation text.

    Extracts only user/assistant text turns. Skips tool calls, tool results,
    system messages, and thinking blocks — these are noise for LLM extraction.
    """
    turns: list[str] = []

    for raw_line in jsonl_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") not in ("user", "assistant"):
            continue

        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                # Only extract plain text — skip tool_use, tool_result, thinking
                if item.get("type") == "text":
                    t = str(item.get("text", "")).strip()
                    if t:
                        parts.append(t)
            text = "\n".join(parts).strip()
        else:
            continue

        if not text or len(text.split()) < MIN_SESSION_WORDS:
            continue

        label = "User" if role == "user" else "Assistant"
        turns.append(f"{label}: {text}")

    return "\n\n".join(turns)


# Transcript entries come from json.loads, so their shape is only known at runtime.
def _entry_ts(entry: dict[str, Any]) -> float:
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return 0.0
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def _typed_text(entry: dict[str, Any], content: Any) -> str | None:
    if entry.get("isSidechain") or entry.get("isMeta") or entry.get("isCompactSummary"):
        return None
    if "toolUseResult" in entry:
        return None
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return None
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        if any(isinstance(i, dict) and i.get("type") == "tool_result" for i in content):
            return None
        parts = [
            str(i.get("text", ""))
            for i in content
            if isinstance(i, dict) and i.get("type") == "text"
        ]
    else:
        return None
    typed = [
        p.strip()
        for p in parts
        if p.strip() and not p.lstrip().startswith(_SYNTHETIC_PREFIXES)
    ]
    return "\n".join(typed) or None


def _result_block_ids(content: Any) -> tuple[str, ...]:
    if isinstance(content, list):
        content = "".join(
            str(i.get("text", ""))
            for i in content
            if isinstance(i, dict) and i.get("type") == "text"
        )
    if not isinstance(content, str):
        return ()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return ()
    entries = payload.get("result") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return ()
    # Only entries that carried the prior's text were injected; a preview-only
    # entry (older clients without inject_all) was listed, not read.
    return tuple(
        e["block_id"]
        for e in entries
        if isinstance(e, dict)
        and isinstance(e.get("block_id"), str)
        and isinstance(e.get("full_text"), str)
        and e["block_id"] not in BLOCK_ID_SENTINELS
    )


def _tool_use_injections(
    items: list[Any], line_no: int, pending_suggest_ids: set[str]
) -> list[Injection]:
    # A suggestion injects only if its result carries full_text, so the call id
    # is kept in pending_suggest_ids for _tool_result_injections to resolve.
    found: list[Injection] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = str(item.get("name", ""))
        args = item.get("input")
        if _TURNZERO_TOOL_MARK not in name or not isinstance(args, dict):
            continue
        if name.endswith(TOOL_INJECT_BLOCK) and isinstance(args.get("block_id"), str):
            found.append(Injection(line_no, (args["block_id"],)))
        elif name.endswith(TOOL_LIST_SUGGESTED):
            pending_suggest_ids.add(str(item.get("id")))
    return found


def _tool_result_injections(
    items: list[Any], line_no: int, pending_suggest_ids: set[str]
) -> list[Injection]:
    found: list[Injection] = []
    for item in items:
        if (
            isinstance(item, dict)
            and item.get("type") == "tool_result"
            and item.get("tool_use_id") in pending_suggest_ids
        ):
            block_ids = _result_block_ids(item.get("content"))
            if block_ids:
                found.append(Injection(line_no, block_ids))
    return found


def parse_claude_session(jsonl_path: Path) -> ParsedSession:
    """Parse a Claude Code session into typed user turns and TurnZero injections.

    Only text the user typed counts as a user turn. A final line that is not
    yet complete JSON is left out of ``lines`` so a later scan reads it again.
    """
    raw_lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    complete = len(raw_lines)
    cwd: str | None = None
    last_ts = 0.0
    seen_assistant = False
    user_turns: list[UserTurn] = []
    injections: list[Injection] = []
    pending_suggest_ids: set[str] = set()

    for line_no, raw in enumerate(raw_lines):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            if line_no == len(raw_lines) - 1:
                complete = line_no
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant"):
            continue
        if cwd is None and isinstance(entry.get("cwd"), str):
            cwd = entry["cwd"]
        ts = _entry_ts(entry)
        last_ts = max(last_ts, ts)
        msg = entry.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        items = content if isinstance(content, list) else []

        if entry["type"] == "assistant":
            if entry.get("isSidechain"):
                continue
            seen_assistant = True
            injections.extend(_tool_use_injections(items, line_no, pending_suggest_ids))
            continue

        injections.extend(_tool_result_injections(items, line_no, pending_suggest_ids))
        text = _typed_text(entry, content)
        if text is not None:
            user_turns.append(UserTurn(line_no, ts, text, seen_assistant))

    return ParsedSession(cwd, complete, last_ts, user_turns, injections)
