"""Harvest Expert Prior candidates from AI conversation logs using a local LLM.

Extraction pipeline:
  1. Read a conversation file (markdown, plain text, or JSON chat export)
  2. Send to local ollama LLM with a structured extraction prompt
  3. Parse response as one or more YAML Expert Prior candidates
  4. Present candidates for human review
  5. Write approved candidates to data/blocks/

The LLM determines intent (build/debug/migrate/review) from conversation
context and suggests conflicts_with based on domain knowledge.
Raw conversation text is never stored — only the extracted Expert Prior YAML.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from turnzero.blocks import compute_confidence

MIN_TURN_WORDS = 3
MIN_CONTEXT_WEIGHT = 50
MIN_SESSION_WORDS = 5
SELF_REF_HITS_THRESHOLD = 4

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
You are a TurnZero Expert Prior extractor. Your job is to analyse an AI \
conversation and extract reusable Expert Priors that represent knowledge an \
expert would inject at the START of that session to prevent mid-session corrections.\
Expert Priors can be from any domain — software, law, medicine, finance, design, \
writing, science, or any other field where domain-specific knowledge prevents mistakes.

An Expert Prior captures:
- constraints: rules the AI should follow (version-specific, domain-specific)
- anti_patterns: things the AI should NOT do (the wrong library, the deprecated API)
- rationale: research-backed explanation of why the rule exists
- doc_anchors: official documentation URLs referenced in the conversation

PERSONAL PRIORS (domain: persona):
If the conversation contains the user's idiosyncratic preferences, personal coding 
style, or project-specific workflow rules (e.g. "I prefer 2-space indents", 
"Never use comments in my code", "Always use mypy strict"), extract these as 
Personal Priors with domain: persona.

INTENT RULES (pick exactly one):
- build:   conversation is about creating something new
- debug:   conversation is about fixing an error or unexpected behaviour
- migrate: conversation is about upgrading versions or switching libraries
- review:  conversation is about evaluating or improving existing code

CONFLICT RULES:
- conflicts_with lists block IDs that would give contradictory instructions
- Most blocks have an empty conflicts_with list
- Only flag a conflict when two blocks would give opposite instructions for \
the SAME decision (e.g. "use bind mounts" vs "use named volumes")

OUTPUT FORMAT — respond with ONLY valid YAML, no prose, no markdown fences:

- id: <descriptive-slug>-<intent>
  version: "1.0.0"
  domain: <primary technology, lowercase, single word>
  intent: <build|debug|migrate|review>
  last_verified: "{today}"
  verification_level: "observed"
  tags: [<tag1>, <tag2>, ...]
  context_weight: <estimated token count of this block, integer>
  conflicts_with: []
  requires: []
  constraints:
    - "<constraint 1>"
    - "<constraint 2>"
  anti_patterns:
    - "<anti-pattern 1>"
    - "<anti-pattern 2>"
  doc_anchors:
    - url: "<url if mentioned in conversation>"
      verified: "{today}"

EXTRACTION RULES:
1. Extract 1-3 blocks maximum. Quality over quantity.
2. Each constraint must be specific, version-anchored where possible, \
and name both the wrong pattern AND the right pattern.
3. Each anti_pattern must start with "Do not".
4. Ignore generic advice that applies to all software.
5. Focus on the mid-session CORRECTIONS — what did the user have to clarify \
after the AI got it wrong? Those corrections are your highest-signal source.
6. context_weight: estimate 4 tokens per word across all constraints + anti_patterns.
7. Do NOT extract personal preferences, individual habits, team conventions, or \
OS-specific paths. A valid Expert Prior must be true for ANYONE working in \
that domain — not just this one person.
8. If the session contains no mid-session corrections and no domain-specific \
gotchas, output nothing. An empty response is better than a junk block.
9. SCOPE CHECK — if the session is casual conversation, venting, or contains \
no domain-specific knowledge that would prevent an AI mistake, output nothing.

GOOD Expert Prior (specific, universally true for the domain, based on a real correction):
  domain: nextjs — "Do not use getServerSideProps — Pages Router only, does not exist in App Router"
  domain: law — "In Swiss employment law, non-compete clauses are unenforceable beyond 3 years"
  domain: finance — "Options Delta is not linear near expiration — gamma accelerates rapidly"
  domain: medicine — "eGFR thresholds for CKD staging differ between CKD-EPI 2009 and 2021 equations"

BAD Expert Prior (personal preference or generic advice):
  "Always write unit tests" — generic, not domain-specific
  "Use VSCode with Prettier" — personal tooling preference
  "Be more concise in your writing" — personal style feedback

CONVERSATION TO ANALYSE:
---
{conversation}
---

Respond with ONLY the YAML block(s). No explanation."""


# ---------------------------------------------------------------------------
# Conversation loading
# ---------------------------------------------------------------------------

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
    if isinstance(data, list) and data and isinstance(data[0], dict) and "role" in data[0]:
        return _turns_from_messages(data)

    # OpenAI SDK format: {messages: [...]}
    if isinstance(data, dict) and "messages" in data:
        return _turns_from_messages(data["messages"])

    # ChatGPT data export: list of conversations, each with a mapping tree
    if isinstance(data, list) and data and isinstance(data[0], dict) and "mapping" in data[0]:
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
                str(c.get("text", "")) for c in content
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
        if author in ("user", "assistant") and text and len(text.split()) >= MIN_TURN_WORDS:
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


def _discover_sessions(min_size_bytes: int) -> list[Path]:
    """Return all session files from all known AI tool locations."""
    home = Path.home()
    found: list[Path] = []

    # Claude Code: ~/.claude/projects/**/*.jsonl
    claude_dir = home / ".claude" / "projects"
    if claude_dir.exists():
        for project_dir in sorted(claude_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            for f in sorted(project_dir.glob("*.jsonl")):
                if f.stat().st_size >= min_size_bytes:
                    found.append(f)

    # Aider: ~/{Development,dev,code}/**/.aider.chat.history.md
    for dev_dir in [home / "Development", home / "dev", home / "code"]:
        if not dev_dir.exists():
            continue
        for f in dev_dir.glob("**/.aider.chat.history.md"):
            if f.stat().st_size >= min_size_bytes:
                found.append(f)

    # Cursor (macOS): ~/Library/Application Support/Cursor/User/workspaceStorage/*/*.json
    cursor_dir = home / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
    if cursor_dir.exists():
        for f in cursor_dir.glob("*/*.json"):
            if f.stat().st_size >= min_size_bytes:
                found.append(f)

    # Windsurf (macOS): ~/Library/Application Support/Windsurf/User/workspaceStorage/*/*.json
    windsurf_dir = home / "Library" / "Application Support" / "Windsurf" / "User" / "workspaceStorage"
    if windsurf_dir.exists():
        for f in windsurf_dir.glob("*/*.json"):
            if f.stat().st_size >= min_size_bytes:
                found.append(f)

    return found


def scan_new_sessions(
    processed_file: Path,
    sessions_dir: Path | None = None,
    min_size_bytes: int = 2000,
) -> list[Path]:
    """Find unprocessed AI session files.

    Auto-discovers sessions from all known AI tools:
      Claude Code   ~/.claude/projects/**/*.jsonl
      Aider         ~/{Development,dev,code}/**/.aider.chat.history.md
      Cursor        ~/Library/Application Support/Cursor/...
      Windsurf      ~/Library/Application Support/Windsurf/...

    Pass sessions_dir to override auto-discovery and scan a single directory.
    Robust sources only — no app databases or unstable internal formats.
    """
    processed: set[str] = set()
    if processed_file.exists():
        processed = set(processed_file.read_text(encoding="utf-8").splitlines())

    if sessions_dir is not None:
        all_files = [
            f for f in sorted(sessions_dir.rglob("*"))
            if f.is_file() and f.stat().st_size >= min_size_bytes
        ]
    else:
        all_files = _discover_sessions(min_size_bytes)

    return [f for f in all_files if str(f) not in processed]


# ---------------------------------------------------------------------------
# Self-referential session filter
# ---------------------------------------------------------------------------

_SELF_REF_TERMS = {
    "turnzero", "promptgraph", "expert prior", "context_weight",
    "blocks_dir", "data/blocks", "index.jsonl", "hook_log",
    "mcp_server", "harvest", "autolearn", "injection gate",
}

def is_self_referential(conversation: str, threshold: float = 0.015) -> bool:
    """Return True if the conversation is predominantly about TurnZero itself.

    Computes the density of self-referential terms as a fraction of total words.
    Sessions above the threshold are skipped — they produce noise, not signal.
    """
    lower = conversation.lower()
    words = lower.split()
    if not words:
        return False
    hits = sum(1 for term in _SELF_REF_TERMS if term in lower)
    density = hits / len(words)
    return density > threshold or hits >= SELF_REF_HITS_THRESHOLD


# ---------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------

def validate_candidate(candidate: dict[str, Any]) -> str | None:
    """Return an error string if the candidate is junk, else None.

    Checks:
    - No placeholder text (<...>) in constraints or anti_patterns
    - context_weight >= MIN_CONTEXT_WEIGHT (anything lower is effectively empty)
    - No empty or placeholder URLs in doc_anchors
    """
    for field in ("constraints", "anti_patterns"):
        for item in candidate.get(field, []):
            if "<" in str(item) and ">" in str(item):
                return f"placeholder text in {field}: {str(item)[:60]}"

    if candidate.get("anti_patterns") and not candidate.get("rationale"):
        return "missing rationale (required when anti_patterns are present)"

    if int(candidate.get("context_weight", 0)) < MIN_CONTEXT_WEIGHT:
        return f"context_weight too low ({candidate.get('context_weight')})"

    for anchor in candidate.get("doc_anchors", []):
        url = str(anchor.get("url", "")).strip()
        if not url or url in ("", "https://example.com", "https://promptgraph.io"):
            return f"invalid doc_anchor url: '{url}'"

    return None


# ---------------------------------------------------------------------------
# LLM extraction — provider-agnostic
# ---------------------------------------------------------------------------

def extract_with_llm(
    conversation: str,
    model: str = "llama3.2",
    max_chars: int = 8000,
    backend: str = "auto",
) -> str:
    """Extract Expert Prior candidates from a conversation using an LLM.

    backend="auto" priority: Anthropic API → OpenAI API → ollama (local).
    Pass backend="ollama" to force local extraction regardless of API keys.

    Raises RuntimeError with actionable instructions if no backend is available.
    """
    from datetime import date
    today = date.today().isoformat()
    truncated = conversation[:max_chars]
    if len(conversation) > max_chars:
        truncated += "\n\n[... conversation truncated for context window ...]"
    prompt = EXTRACTION_PROMPT.format(conversation=truncated, today=today)

    if backend == "ollama":
        return _extract_ollama(prompt, model)

    if backend == "anthropic" or (backend == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return _extract_anthropic(prompt)

    if backend == "openai" or (backend == "auto" and os.environ.get("OPENAI_API_KEY")):
        return _extract_openai(prompt)

    # Local fallback
    try:
        return _extract_ollama(prompt, model)
    except RuntimeError:
        pass

    raise RuntimeError(
        "No LLM backend available for harvest extraction.\n\n"
        "Option 1 (Anthropic, fast):\n"
        "  export ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "Option 2 (OpenAI):\n"
        "  export OPENAI_API_KEY=sk-...\n\n"
        "Option 3 (local, free):\n"
        "  ollama serve && ollama pull llama3.2"
    )


def _extract_ollama(prompt: str, model: str) -> str:
    try:
        import ollama as _ollama
    except ImportError as e:
        raise RuntimeError("ollama package not installed") from e
    try:
        response = _ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        return str(response["message"]["content"])
    except Exception as e:
        raise RuntimeError(f"ollama unavailable: {e}") from e


def _extract_openai(prompt: str) -> str:
    import httpx
    api_key = os.environ["OPENAI_API_KEY"]
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        raise RuntimeError(f"OpenAI extraction failed: {e}") from e


def _extract_anthropic(prompt: str) -> str:
    import httpx
    api_key = os.environ["ANTHROPIC_API_KEY"]
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return str(resp.json()["content"][0]["text"])
    except Exception as e:
        raise RuntimeError(f"Anthropic extraction failed: {e}") from e


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

def _strip_prose(text: str) -> str:
    """Drop any prose lines before the first YAML content line."""
    for i, line in enumerate(text.splitlines()):
        if line.startswith("---") or line.startswith("- "):
            return "\n".join(text.splitlines()[i:])
    return text


_BLOCK_TOP_KEYS = frozenset({
    "id", "version", "domain", "intent", "last_verified", "tags",
    "context_weight", "conflicts_with", "requires", "constraints",
    "anti_patterns", "doc_anchors", "slug", "title", "description",
})


def _fix_key_indentation(text: str) -> str:
    """Fix LLM indentation bug where anti_patterns/doc_anchors end up nested
    under the last constraints list item instead of being siblings.

    Detects base indentation from constraints: then re-indents any top-level
    block keys that are wrongly over-indented.
    """
    lines = text.splitlines()

    # Detect base indent from constraints: (present in both list and mapping fmt)
    base_indent = 0
    for line in lines:
        m = re.match(r'^(\s*)constraints\s*:', line)
        if m:
            base_indent = len(m.group(1))
            break

    result = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped[0] in ('-', '#'):
            result.append(line)
            continue
        key = stripped.split(':')[0].strip()
        current_indent = len(line) - len(stripped)
        if key in _BLOCK_TOP_KEYS and current_indent != base_indent:
            result.append(' ' * base_indent + stripped)
        else:
            result.append(line)
    return '\n'.join(result)


def parse_candidates(raw_yaml: str) -> list[dict[str, Any]]:
    """Parse LLM output into a list of block candidate dicts.

    Handles LLM quirks: markdown fences, extra prose, partial YAML,
    and multi-document YAML (--- separators between blocks).

    Each --- section is parsed independently so one malformed block
    does not discard the rest.
    """
    cleaned = re.sub(r"```(?:yaml)?\n?", "", raw_yaml).strip()
    cleaned = _strip_prose(cleaned)
    cleaned = _fix_key_indentation(cleaned)

    # Split on --- and parse each chunk independently
    chunks = re.split(r"\n?---\n?", cleaned)
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for chunk in chunks:
        stripped_chunk = chunk.strip()
        if not stripped_chunk:
            continue
        try:
            doc = yaml.safe_load(stripped_chunk)
        except yaml.YAMLError:
            errors.append(chunk[:60])
            continue
        if isinstance(doc, dict):
            results.append(_normalise(doc))
        elif isinstance(doc, list):
            results.extend(_normalise(c) for c in doc if isinstance(c, dict))

    if not results and errors:
        raise ValueError(
            f"Could not parse LLM output as YAML "
            f"({len(errors)} chunk(s) failed).\n\nRaw output:\n{raw_yaml}"
        )

    return results


def _compute_context_weight(candidate: dict[str, Any]) -> int:
    """Estimate token count from actual content (4 tokens/word)."""
    text = " ".join(
        str(s) for s in candidate.get("constraints", []) + candidate.get("anti_patterns", [])
    )
    return max(50, len(text.split()) * 4)


def _normalise(candidate: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults and ensure required fields exist."""
    candidate.setdefault("version", "1.0.0")
    from datetime import date
    candidate.setdefault("last_verified", date.today().isoformat())
    candidate.setdefault("verification_level", "observed")
    candidate.setdefault("tags", [])
    candidate.setdefault("conflicts_with", [])
    candidate.setdefault("requires", [])
    candidate.setdefault("constraints", [])
    candidate.setdefault("anti_patterns", [])
    candidate.setdefault("doc_anchors", [])
    candidate.setdefault("archived", False)

    # Always recompute weight — don't trust the LLM's estimate
    candidate["context_weight"] = _compute_context_weight(candidate)

    # Compute confidence for harvested block
    candidate["confidence"] = compute_confidence(
        slug=candidate.get("id", ""),
        constraints=candidate["constraints"],
        anti_patterns=candidate["anti_patterns"],
        tags=candidate["tags"],
        reason="Harvested from session transcript",
    )

    # Ensure intent is valid
    valid_intents = {"build", "debug", "migrate", "review"}
    if candidate.get("intent") not in valid_intents:
        candidate["intent"] = "build"

    # Generate ID if missing or placeholder
    if not candidate.get("id") or candidate["id"] == "<descriptive-slug>-<intent>":
        domain = str(candidate.get("domain", candidate.get("stack", "unknown")))
        intent = str(candidate.get("intent", "build"))
        candidate["id"] = f"{domain}-{intent}-extracted"

    return candidate


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------

def content_hash(candidate: dict[str, Any]) -> str:
    """First 16 hex chars of SHA-256 of canonical YAML content."""
    payload = {k: v for k, v in candidate.items() if k != "id"}
    canonical = yaml.dump(payload, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Block writing
# ---------------------------------------------------------------------------

def write_candidate(candidate: dict[str, Any], blocks_dir: Path) -> Path:
    """Write a candidate dict to a YAML file in blocks_dir. Returns the path."""
    block_id = str(candidate["id"])
    path = blocks_dir / f"{block_id}.yaml"
    path.write_text(
        yaml.dump(candidate, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# High-level harvest function
# ---------------------------------------------------------------------------

def harvest(
    conversation_path: Path,
    blocks_dir: Path,
    model: str = "llama3.2",
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Full harvest pipeline: load → extract → parse → return candidates.

    If dry_run=False and the caller approves, write blocks via write_candidate().
    Returns list of parsed candidate dicts.
    """
    conversation = load_conversation(conversation_path)
    raw = extract_with_llm(conversation, model=model)
    candidates = parse_candidates(raw)
    return candidates
