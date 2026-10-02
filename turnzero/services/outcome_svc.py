"""Outcome service — detect corrections in session transcripts and measure priors."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from rich.console import Console

from turnzero.config import get_data_dir, load_config
from turnzero.embed import embed
from turnzero.harvest import Injection, ParsedSession, UserTurn, parse_claude_session
from turnzero.repositories.index_repo import sync_rule_vectors
from turnzero.services import retrieval_svc
from turnzero.session import _get_project_hash
from turnzero.signals import (
    CORRECTION_CUES,
    CORRECTION_EXCLUSIONS,
    CORRECTION_OPENERS,
)
from turnzero.types import OutcomeStats, TopBlockEntry, Verdict

OUTCOMES_FILE = "outcomes.jsonl"
RULE_VECTORS_FILE = "rule_vectors.npz"
_LOCK_FILE = "outcomes.lock"
_DIGEST_STATE_FILE = "outcome_digest.json"

# Cosine similarity a correction must reach against a single library rule to
# count as restating it. Used until enough ordinary turns have been scored to
# derive the threshold from the user's own noise floor (see match_threshold).
DEFAULT_MATCH_THRESHOLD = 0.72
MIN_NOISE_SAMPLES = 100
_NOISE_SIGMAS = 3.0
_NOISE_KEYS = ("noise_n", "noise_sum", "noise_sumsq")

OUTCOME_WINDOW_DAYS = 30
MIN_SESSIONS = 10
_TOP_BLOCKS = 5

# Longer turns are new task descriptions or pasted content, and their embedding
# is too diluted to match a single rule.
MAX_CORRECTION_WORDS = 80


def _alternation(phrases: tuple[str, ...]) -> str:
    return "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))


_OPENER_RE = re.compile(rf"^(?:{_alternation(CORRECTION_OPENERS)})(?!\w)")
_CUE_RE = re.compile(rf"(?<!\w)(?:{_alternation(CORRECTION_CUES)})(?!\w)")


def is_correction(text: str) -> bool:
    """Return True when a user turn reads as a correction of the assistant."""
    lowered = " ".join(text.lower().replace("\u2019", "'").split())
    if len(lowered.split()) > MAX_CORRECTION_WORDS:
        return False
    for phrase in CORRECTION_EXCLUSIONS:
        lowered = lowered.replace(phrase, " ")
    lowered = lowered.strip()
    return bool(_OPENER_RE.match(lowered) or _CUE_RE.search(lowered))


def _default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Rows come from json.loads, so their shape is only known at runtime.
def _is_valid_row(row: dict[str, Any]) -> bool:
    if not isinstance(row.get("session"), str) or not _is_number(row.get("ts")):
        return False
    if row.get("kind") == "session":
        injected = row.get("injected")
        return (
            isinstance(injected, list)
            and all(isinstance(b, str) for b in injected)
            and isinstance(row.get("lines_scanned"), int)
            and _is_number(row.get("mtime"))
            and all(_is_number(row.get(key, 0)) for key in _NOISE_KEYS)
        )
    if row.get("kind") == "correction":
        block_id = row.get("block_id")
        return (
            _is_number(row.get("score"))
            and (block_id is None or isinstance(block_id, str))
            and isinstance(row.get("injected"), bool)
        )
    return False


def _read_rows(outcomes_path: Path) -> list[dict[str, Any]]:
    # The file can be damaged by a crash, a full disk, or a hand edit, and it is
    # read on every list_suggested_blocks call: anything unreadable is skipped.
    rows: list[dict[str, Any]] = []
    if not outcomes_path.exists():
        return rows
    text = outcomes_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and _is_valid_row(row):
            rows.append(row)
    return rows


def _append_rows(outcomes_path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(r) + "\n" for r in rows)
    with outcomes_path.open("a+b") as f:
        # A previous write cut off mid-line would otherwise swallow the first row.
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                payload = "\n" + payload
        f.write(payload.encode("utf-8"))


def _latest_sessions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["session"]: r for r in rows if r["kind"] == "session"}


def _load_rules(data_dir: Path) -> tuple[list[str], np.ndarray]:
    vectors = sync_rule_vectors(
        retrieval_svc._load_active_blocks(),
        data_dir / RULE_VECTORS_FILE,
        local_only=True,
    )
    if not vectors:
        return [], np.zeros((0, 0), dtype=np.float32)
    matrix = np.stack([v.embedding for v in vectors])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return [v.block_id for v in vectors], matrix / norms


def _best_match(
    vec: np.ndarray, block_ids: list[str], matrix: np.ndarray
) -> tuple[str | None, float]:
    norm = float(np.linalg.norm(vec))
    if not block_ids or norm == 0.0:
        return None, 0.0
    scores = matrix @ (vec / norm)
    top = int(scores.argmax())
    return block_ids[top], float(scores[top])


def match_threshold(rows: list[dict[str, Any]]) -> tuple[float, int]:
    """Return the match threshold and the number of ordinary turns behind it.

    Ordinary (non-correction) mid-session turns are the noise floor: how close
    unrelated text gets to a library rule for this user, library, and embedding
    model. A correction restates a rule only if it scores clearly above that.
    """
    sessions = list(_latest_sessions(rows).values())
    count = int(sum(s.get("noise_n", 0) for s in sessions))
    if count < MIN_NOISE_SAMPLES:
        return DEFAULT_MATCH_THRESHOLD, count
    mean = sum(s.get("noise_sum", 0.0) for s in sessions) / count
    variance = sum(s.get("noise_sumsq", 0.0) for s in sessions) / count - mean * mean
    return round(mean + _NOISE_SIGMAS * max(variance, 0.0) ** 0.5, 2), count


def verdict_of(row: dict[str, Any], threshold: float) -> Verdict:
    """Classify a stored correction row against the current match threshold."""
    if row["block_id"] is None or row["score"] < threshold:
        return Verdict.NEW
    return Verdict.FAILED if row["injected"] else Verdict.MISS


def _correction_row(
    session: str,
    turn: UserTurn,
    injections: list[Injection],
    vec: np.ndarray,
    block_id: str | None,
    score: float,
    threshold: float,
) -> dict[str, Any]:
    injected_before = {
        b for inj in injections if inj.line < turn.line for b in inj.block_ids
    }
    # No verdict is stored: the threshold moves as the noise floor is learned,
    # so the verdict is derived from score and injected when stats are read.
    row: dict[str, Any] = {
        "kind": "correction",
        "session": session,
        "ts": turn.ts,
        "turn": turn.line,
        "score": round(score, 3),
        "block_id": block_id,
        "injected": block_id in injected_before,
    }
    if block_id is None or score < threshold:
        # Transcripts expire after about 30 days; the vector is the only way to
        # recognise the same uncovered correction in a later session.
        row["embedding"] = [round(float(x), 5) for x in vec]
    return row


def _session_rows(
    session: str,
    parsed: ParsedSession,
    previous: dict[str, Any],
    turns: list[UserTurn],
    rules: tuple[list[str], np.ndarray],
    threshold: float,
    mtime: float,
) -> list[dict[str, Any]]:
    block_ids, matrix = rules
    noise_n = int(previous.get("noise_n", 0))
    noise_sum = float(previous.get("noise_sum", 0.0))
    noise_sumsq = float(previous.get("noise_sumsq", 0.0))
    rows: list[dict[str, Any]] = []
    for turn in turns:
        # The scan runs unprompted, so transcript text must never reach a remote backend.
        vec = embed(turn.text, local_only=True)
        block_id, score = _best_match(vec, block_ids, matrix)
        if is_correction(turn.text):
            rows.append(
                _correction_row(
                    session, turn, parsed.injections, vec, block_id, score, threshold
                )
            )
        elif block_id is not None:
            noise_n += 1
            noise_sum += score
            noise_sumsq += score * score

    rows.append(
        {
            "kind": "session",
            "session": session,
            "project": _get_project_hash(Path(parsed.cwd)) if parsed.cwd else None,
            "ts": parsed.last_ts,
            "user_turns": len(parsed.user_turns),
            "injected": sorted({b for inj in parsed.injections for b in inj.block_ids}),
            "lines_scanned": parsed.lines,
            "mtime": mtime,
            "noise_n": noise_n,
            "noise_sum": round(noise_sum, 6),
            "noise_sumsq": round(noise_sumsq, 6),
        }
    )
    return rows


def _scan_locked(root: Path, data_dir: Path) -> int:
    outcomes_path = data_dir / OUTCOMES_FILE
    stored = _read_rows(outcomes_path)
    state = _latest_sessions(stored)
    threshold, _ = match_threshold(stored)
    rules: tuple[list[str], np.ndarray] | None = None
    written = 0

    for path in sorted(root.glob("*/*.jsonl")):
        session = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
        previous = state.get(session, {})
        try:
            mtime = path.stat().st_mtime
            if mtime == previous.get("mtime"):
                continue
            parsed = parse_claude_session(path)
        except OSError:
            continue
        if not parsed.user_turns:
            continue

        lines_scanned = int(previous.get("lines_scanned", 0))
        turns = [
            t
            for t in parsed.user_turns
            if t.line >= lines_scanned
            and t.after_assistant
            and len(t.text.split()) <= MAX_CORRECTION_WORDS
        ]
        if turns and rules is None:
            rules = _load_rules(data_dir)
        rows = _session_rows(
            session,
            parsed,
            previous,
            turns,
            rules or ([], np.zeros((0, 0), dtype=np.float32)),
            threshold,
            mtime,
        )
        _append_rows(outcomes_path, rows)
        written += len(rows) - 1

    return written


def scan(data_dir: Path | None = None, projects_dir: Path | None = None) -> int:
    """Scan Claude Code transcripts for corrections and append outcome rows.

    Transcript text is read in memory and discarded; only embeddings, block
    ids, hashes, and counts are written. Embedding uses local backends only.
    Returns the number of correction rows written, or 0 if another scan holds
    the lock.
    """
    resolved = data_dir if data_dir is not None else get_data_dir()
    root = projects_dir if projects_dir is not None else _default_projects_dir()
    if not root.exists() or not load_config(resolved).get("outcome_scan", True):
        return 0
    resolved.mkdir(parents=True, exist_ok=True)
    with (resolved / _LOCK_FILE).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            return _scan_locked(root, resolved)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def scan_quietly(
    data_dir: Path | None = None, projects_dir: Path | None = None
) -> None:
    """Run scan() and swallow every failure; for background and pre-render use."""
    try:
        scan(data_dir, projects_dir)
    except Exception as exc:
        if os.environ.get("TURNZERO_DEBUG"):
            Console(stderr=True).print(f"[dim]turnzero outcome scan failed: {exc!r}[/dim]")


def _in_window(
    rows: list[dict[str, Any]], start: float, end: float
) -> list[dict[str, Any]]:
    return [r for r in rows if start < float(r.get("ts", 0.0)) <= end]


def _rate(session_count: int, repeat_count: int) -> float | None:
    if session_count < MIN_SESSIONS:
        return None
    return round(repeat_count / session_count, 2)


def _top(counts: Counter[str]) -> list[TopBlockEntry]:
    return [
        {"block_id": block_id, "count": count}
        for block_id, count in counts.most_common(_TOP_BLOCKS)
    ]


def summarize(data_dir: Path, now: float | None = None) -> OutcomeStats:
    """Aggregate outcome rows over the last window and the one before it."""
    end = now if now is not None else time.time()
    span = OUTCOME_WINDOW_DAYS * 86400.0
    rows = _read_rows(data_dir / OUTCOMES_FILE)
    sessions = list(_latest_sessions(rows).values())
    corrections = [r for r in rows if r["kind"] == "correction"]
    threshold, noise_samples = match_threshold(rows)

    cur_sessions = _in_window(sessions, end - span, end)
    cur_corrections = _in_window(corrections, end - span, end)
    old_sessions = _in_window(sessions, end - 2 * span, end - span)
    old_corrections = _in_window(corrections, end - 2 * span, end - span)

    failed: Counter[str] = Counter()
    missed: Counter[str] = Counter()
    for c in cur_corrections:
        verdict = verdict_of(c, threshold)
        if verdict == Verdict.FAILED:
            failed[c["block_id"]] += 1
        elif verdict == Verdict.MISS:
            missed[c["block_id"]] += 1
    repeat_count = sum(failed.values()) + sum(missed.values())
    old_repeat_count = sum(
        1 for c in old_corrections if verdict_of(c, threshold) != Verdict.NEW
    )
    injected = {b for s in cur_sessions for b in s["injected"]}

    return {
        "window_days": OUTCOME_WINDOW_DAYS,
        "sessions": len(cur_sessions),
        "repeat_corrections": repeat_count,
        "repeat_rate": _rate(len(cur_sessions), repeat_count),
        "previous_rate": _rate(len(old_sessions), old_repeat_count),
        "held": len(injected - set(failed)),
        "failed_total": len(failed),
        "failed": _top(failed),
        "missed_total": len(missed),
        "missed": _top(missed),
        "uncovered": len(cur_corrections) - repeat_count,
        "threshold": threshold,
        "noise_samples": noise_samples,
    }


def weekly_line(data_dir: Path, now: float | None = None) -> str | None:
    """Return the outcome digest line on one day per ISO week, or None.

    The line is returned on every call during the first day it appears in a
    week, so one automated session (a benchmark run, a subagent) cannot use up
    the only showing. The day is recorded only when a line is returned, so a
    week that starts without enough data still gets its line later.
    """
    moment = now if now is not None else time.time()
    today = datetime.fromtimestamp(moment)
    iso = today.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    date = today.date().isoformat()
    state_path = data_dir / _DIGEST_STATE_FILE
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        shown_week, shown_date = state.get("week"), state.get("date")
    except (OSError, json.JSONDecodeError, AttributeError):
        shown_week, shown_date = None, None
    if shown_week == week and shown_date != date:
        return None

    stats = summarize(data_dir, now=moment)
    rate = stats["repeat_rate"]
    if rate is None:
        return None

    if shown_week != week:
        with contextlib.suppress(OSError):
            state_path.write_text(
                json.dumps({"week": week, "date": date}), encoding="utf-8"
            )

    change = ""
    previous = stats["previous_rate"]
    if previous:
        percent = round((previous - rate) / previous * 100)
        arrow = "▼" if percent > 0 else "▲" if percent < 0 else "="
        change = f" ({arrow} {abs(percent)}%)"
    return (
        f"📎 TurnZero, last {stats['window_days']} days: {rate:.2f} repeat "
        f"corrections/session{change}. Priors: {stats['held']} held, "
        f"{stats['failed_total']} failed. ~{stats['uncovered']} corrections had no prior."
    )
