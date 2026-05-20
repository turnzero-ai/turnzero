"""Session discovery and self-referential content filtering."""

from __future__ import annotations

from pathlib import Path

MIN_SIZE_BYTES_DEFAULT = 2000
SELF_REF_HITS_THRESHOLD = 4

_SELF_REF_TERMS = {
    "turnzero",
    "promptgraph",
    "expert prior",
    "context_weight",
    "blocks_dir",
    "data/blocks",
    "index.jsonl",
    "hook_log",
    "mcp_server",
    "harvest",
    "injection gate",
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
    cursor_dir = (
        home / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
    )
    if cursor_dir.exists():
        for f in cursor_dir.glob("*/*.json"):
            if f.stat().st_size >= min_size_bytes:
                found.append(f)

    # Windsurf (macOS): ~/Library/Application Support/Windsurf/User/workspaceStorage/*/*.json
    windsurf_dir = (
        home / "Library" / "Application Support" / "Windsurf" / "User" / "workspaceStorage"
    )
    if windsurf_dir.exists():
        for f in windsurf_dir.glob("*/*.json"):
            if f.stat().st_size >= min_size_bytes:
                found.append(f)

    return found


def scan_new_sessions(
    processed_file: Path,
    sessions_dir: Path | None = None,
    min_size_bytes: int = MIN_SIZE_BYTES_DEFAULT,
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
            f
            for f in sorted(sessions_dir.rglob("*"))
            if f.is_file() and f.stat().st_size >= min_size_bytes
        ]
    else:
        all_files = _discover_sessions(min_size_bytes)

    return [f for f in all_files if str(f) not in processed]
