"""Tests for outcome_svc — correction detection, scan, and aggregation."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.transcripts import (
    append_entries,
    assistant,
    suggest_call,
    tool_result,
    user,
    write_transcript,
)
from turnzero.embed import EMBEDDING_DIM
from turnzero.services import outcome_svc

# ---------------------------------------------------------------------------
# is_correction
# ---------------------------------------------------------------------------


def test_correction_gate_meets_quality_floor() -> None:
    cases = json.loads(
        (Path(__file__).parent / "correction_set.json").read_text(encoding="utf-8")
    )
    flagged = [c for c in cases if outcome_svc.is_correction(c["text"])]
    true_positives = sum(1 for c in flagged if c["correction"])
    positives = sum(1 for c in cases if c["correction"])

    assert true_positives / len(flagged) >= 0.80
    assert true_positives / positives >= 0.50


def test_is_correction_ignores_exclusion_phrases() -> None:
    assert not outcome_svc.is_correction("no problem, carry on")
    assert not outcome_svc.is_correction("don't worry about it")


def test_is_correction_handles_curly_apostrophe() -> None:
    assert outcome_svc.is_correction("don’t mock the database")


def test_is_correction_does_not_match_inside_words() -> None:
    assert not outcome_svc.is_correction("what is known about the nodes?")


def test_is_correction_rejects_long_pasted_turn() -> None:
    pasted = "don't " + "log line " * outcome_svc.MAX_CORRECTION_WORDS
    assert not outcome_svc.is_correction(pasted)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

RULE = "do not create a new venv"
UNRELATED = "no, rename the variable to total"


def _write_block(data_dir: Path, slug: str, constraints: list[str]) -> None:
    path = data_dir / "blocks" / "local" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    rules = "".join(f"  - {json.dumps(c)}\n" for c in constraints)
    path.write_text(
        f"slug: {slug}\nversion: 1.0.0\ndomain: python\nintent: build\n"
        f"last_verified: 2026-05-01\ncontext_weight: 100\nconstraints:\n{rules}"
        "anti_patterns: []\nconfidence: 0.9\narchived: false\n",
        encoding="utf-8",
    )


# Rows are read back with json.loads, so their shape is only known at runtime.
def _rows(data_dir: Path, kind: str) -> list[dict[str, Any]]:
    path = data_dir / outcome_svc.OUTCOMES_FILE
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["kind"] == kind]


def _verdict(row: dict[str, Any]) -> str:
    return outcome_svc.verdict_of(row, outcome_svc.DEFAULT_MATCH_THRESHOLD)


def _corrected_session() -> list[dict[str, Any]]:
    return [
        user("set up the project", 0),
        assistant("Created a new venv.", 1),
        user(RULE, 2),
    ]


def test_scan_marks_injected_prior_as_failed(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(
        projects,
        "s1",
        [
            user("set up the project", 0),
            assistant("Looking.", 1, tool_uses=[suggest_call("t1")]),
            tool_result("t1", ["venv-rule"], 2),
            assistant("Created a new venv.", 3),
            user(RULE, 4),
        ],
    )

    assert outcome_svc.scan(data_dir, projects) == 1

    (correction,) = _rows(data_dir, "correction")
    assert _verdict(correction) == "failed"
    assert correction["block_id"] == "venv-rule"
    assert correction["injected"] is True
    assert correction["turn"] == 4
    assert "embedding" not in correction
    (session,) = _rows(data_dir, "session")
    assert session["injected"] == ["venv-rule"]
    assert session["user_turns"] == 2
    assert session["lines_scanned"] == 5


def test_scan_marks_uninjected_prior_as_miss(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())

    assert outcome_svc.scan(data_dir, projects) == 1
    (correction,) = _rows(data_dir, "correction")
    assert _verdict(correction) == "miss"
    assert correction["block_id"] == "venv-rule"
    assert correction["injected"] is False


def test_scan_injection_after_correction_is_not_failed(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(
        projects,
        "s1",
        [
            *_corrected_session(),
            assistant("Looking.", 3, tool_uses=[suggest_call("t1")]),
            tool_result("t1", ["venv-rule"], 4),
        ],
    )

    outcome_svc.scan(data_dir, projects)
    (correction,) = _rows(data_dir, "correction")
    assert _verdict(correction) == "miss"


def test_scan_stores_embedding_for_unmatched_correction(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(
        projects,
        "s1",
        [user("set up the project", 0), assistant("Done.", 1), user(UNRELATED, 2)],
    )

    outcome_svc.scan(data_dir, projects)
    (correction,) = _rows(data_dir, "correction")
    assert _verdict(correction) == "new"
    assert "verdict" not in correction
    assert len(correction["embedding"]) == EMBEDDING_DIM


def test_scan_ignores_turn_before_first_assistant_reply(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", [user(RULE, 0), assistant("Understood.", 1)])

    assert outcome_svc.scan(data_dir, projects) == 0
    assert _rows(data_dir, "correction") == []
    assert len(_rows(data_dir, "session")) == 1


def test_scan_stores_no_transcript_text(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(
        projects,
        "s1",
        [
            user("set up the secret project", 0),
            assistant("Created a new venv.", 1),
            user(RULE, 2),
            assistant("Fixed.", 3),
            user(UNRELATED, 4),
        ],
    )

    outcome_svc.scan(data_dir, projects)
    stored = (data_dir / outcome_svc.OUTCOMES_FILE).read_text(encoding="utf-8")

    for text in ("set up the secret project", RULE, UNRELATED, "Created a new venv."):
        assert text not in stored
    assert "/work/proj" not in stored


def test_scan_is_incremental(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    path = write_transcript(projects, "s1", _corrected_session())

    assert outcome_svc.scan(data_dir, projects) == 1
    outcomes = data_dir / outcome_svc.OUTCOMES_FILE
    after_first = outcomes.read_text(encoding="utf-8")

    assert outcome_svc.scan(data_dir, projects) == 0
    assert outcomes.read_text(encoding="utf-8") == after_first

    append_entries(path, [assistant("Fixed.", 3), user(UNRELATED, 4)])
    assert outcome_svc.scan(data_dir, projects) == 1

    assert [c["turn"] for c in _rows(data_dir, "correction")] == [2, 4]
    assert _rows(data_dir, "session")[-1]["lines_scanned"] == 5


def test_scan_picks_up_half_written_line_on_next_scan(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    path = write_transcript(
        projects, "s1", [user("set up the project", 0), assistant("Created a venv.", 1)]
    )
    complete = path.read_text(encoding="utf-8")
    last_line = json.dumps(user(RULE, 2))
    path.write_text(complete + last_line[:30], encoding="utf-8")

    assert outcome_svc.scan(data_dir, projects) == 0

    path.write_text(complete, encoding="utf-8")
    append_entries(path, [user(RULE, 2)])
    assert outcome_svc.scan(data_dir, projects) == 1


def test_scan_without_projects_dir_is_a_noop(data_dir: Path) -> None:
    assert outcome_svc.scan(data_dir, data_dir / "does-not-exist") == 0
    assert not (data_dir / outcome_svc.OUTCOMES_FILE).exists()


def test_scan_survives_garbage_line_in_outcomes_file(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())
    (data_dir / outcome_svc.OUTCOMES_FILE).write_text("{truncated\n", encoding="utf-8")

    assert outcome_svc.scan(data_dir, projects) == 1
    assert outcome_svc.scan(data_dir, projects) == 0


def test_scan_skips_when_another_scan_holds_the_lock(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())

    with (data_dir / "outcomes.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert outcome_svc.scan(data_dir, projects) == 0

    assert not (data_dir / outcome_svc.OUTCOMES_FILE).exists()


def test_scan_writes_nothing_when_embedding_fails(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())

    def no_backend(text: str, **kwargs: Any) -> Any:
        raise RuntimeError("No embedding backend available.")

    monkeypatch.setattr(outcome_svc, "embed", no_backend)

    with pytest.raises(RuntimeError):
        outcome_svc.scan(data_dir, projects)
    assert _rows(data_dir, "session") == []

    outcome_svc.scan_quietly(data_dir, projects)
    assert _rows(data_dir, "session") == []

    from turnzero.embed import embed as real_embed

    monkeypatch.setattr(outcome_svc, "embed", real_embed)
    assert outcome_svc.scan(data_dir, projects) == 1


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

NOW = 1_800_000_000.0
DAY = 86400.0


def _session_row(name: str, ts: float, injected: list[str]) -> dict[str, Any]:
    return {
        "kind": "session",
        "session": name,
        "project": "p",
        "ts": ts,
        "user_turns": 3,
        "injected": injected,
        "lines_scanned": 9,
        "mtime": ts,
    }


def _correction_row(
    session: str, ts: float, verdict: str, block_id: str | None
) -> dict[str, Any]:
    """A stored correction row that reads as the given verdict at the default threshold."""
    return {
        "kind": "correction",
        "session": session,
        "ts": ts,
        "turn": 4,
        "score": 0.3 if verdict == "new" else 0.9,
        "block_id": block_id,
        "injected": verdict == "failed",
    }


def _write_rows(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    (data_dir / outcome_svc.OUTCOMES_FILE).write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def test_summarize_without_data(data_dir: Path) -> None:
    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["sessions"] == 0
    assert stats["repeat_rate"] is None
    assert stats["previous_rate"] is None
    assert stats["failed"] == []


def test_summarize_needs_minimum_sessions(data_dir: Path) -> None:
    _write_rows(
        data_dir, [_session_row(f"s{i}", NOW - DAY, ["a"]) for i in range(9)]
    )
    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["sessions"] == 9
    assert stats["repeat_rate"] is None


def test_summarize_rates_and_blocks(data_dir: Path) -> None:
    current = NOW - 5 * DAY
    previous = NOW - 40 * DAY
    rows = [_session_row(f"cur{i}", current, ["a", "b"]) for i in range(10)]
    rows += [_session_row(f"old{i}", previous, ["a"]) for i in range(10)]
    rows += [
        _correction_row("cur0", current, "failed", "a"),
        _correction_row("cur1", current, "failed", "a"),
        _correction_row("cur2", current, "miss", "c"),
        _correction_row("cur3", current, "new", None),
        _correction_row("cur4", current, "new", None),
    ]
    rows += [_correction_row(f"old{i}", previous, "failed", "a") for i in range(6)]
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["window_days"] == 30
    assert stats["sessions"] == 10
    assert stats["repeat_corrections"] == 3
    assert stats["repeat_rate"] == 0.3
    assert stats["previous_rate"] == 0.6
    assert stats["held"] == 1
    assert stats["failed_total"] == 1
    assert stats["failed"] == [{"block_id": "a", "count": 2}]
    assert stats["missed_total"] == 1
    assert stats["missed"] == [{"block_id": "c", "count": 1}]
    assert stats["uncovered"] == 2


def test_summarize_counts_a_rescanned_session_once(data_dir: Path) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, ["a"]) for i in range(10)]
    rows.append(_session_row("s0", NOW - DAY / 2, ["a", "b"]))
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["sessions"] == 10
    assert stats["held"] == 2


def test_summarize_lists_at_most_five_blocks(data_dir: Path) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, []) for i in range(10)]
    rows += [
        _correction_row("s0", NOW - DAY, "failed", f"block-{n}") for n in range(7)
    ]
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["failed_total"] == 7
    assert len(stats["failed"]) == 5


# ---------------------------------------------------------------------------
# weekly_line
# ---------------------------------------------------------------------------


def _ten_sessions_with_history(data_dir: Path) -> None:
    current = NOW - 5 * DAY
    previous = NOW - 40 * DAY
    rows = [_session_row(f"cur{i}", current, ["a", "b"]) for i in range(10)]
    rows += [_session_row(f"old{i}", previous, ["a"]) for i in range(10)]
    rows += [_correction_row(f"cur{i}", current, "failed", "a") for i in range(3)]
    rows += [_correction_row(f"old{i}", previous, "failed", "a") for i in range(6)]
    rows += [_correction_row(f"cur{i}", current, "new", None) for i in range(2)]
    _write_rows(data_dir, rows)


def test_weekly_line_reports_rate_and_change(data_dir: Path) -> None:
    _ten_sessions_with_history(data_dir)

    line = outcome_svc.weekly_line(data_dir, now=NOW)

    assert line == (
        "📎 TurnZero, last 30 days: 0.30 repeat corrections/session (▼ 50%). "
        "Priors: 1 held, 1 failed. ~2 corrections had no prior."
    )


def test_weekly_line_shows_all_day_on_its_first_day_then_waits_a_week(
    data_dir: Path,
) -> None:
    """One automated session must not use up the week's only showing."""
    _ten_sessions_with_history(data_dir)

    assert outcome_svc.weekly_line(data_dir, now=NOW) is not None
    assert outcome_svc.weekly_line(data_dir, now=NOW + 3600) is not None
    assert outcome_svc.weekly_line(data_dir, now=NOW + DAY) is None
    assert outcome_svc.weekly_line(data_dir, now=NOW + 7 * DAY) is not None


def test_weekly_line_omits_change_without_previous_window(data_dir: Path) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, ["a"]) for i in range(10)]
    _write_rows(data_dir, rows)

    line = outcome_svc.weekly_line(data_dir, now=NOW)

    assert line == (
        "📎 TurnZero, last 30 days: 0.00 repeat corrections/session. "
        "Priors: 1 held, 0 failed. ~0 corrections had no prior."
    )


def test_weekly_line_waits_for_enough_data(data_dir: Path) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, ["a"]) for i in range(4)]
    _write_rows(data_dir, rows)

    assert outcome_svc.weekly_line(data_dir, now=NOW) is None

    rows += [_session_row(f"t{i}", NOW - DAY, ["a"]) for i in range(6)]
    _write_rows(data_dir, rows)
    assert outcome_svc.weekly_line(data_dir, now=NOW) is not None


def test_scan_never_sends_text_to_a_remote_embedding_backend(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    from turnzero import embed as embed_mod

    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())

    sent: list[str] = []

    def ollama_down(text: str) -> Any:
        raise RuntimeError("ollama unavailable")

    def fake_openai(text: str) -> Any:
        sent.append(text)
        return np.ones(EMBEDDING_DIM, dtype=np.float32)

    monkeypatch.delenv("TURNZERO_TEST_EMBEDDINGS")
    monkeypatch.setattr(embed_mod, "_is_onnx_available", lambda: False)
    monkeypatch.setattr(embed_mod, "_is_ollama_running", lambda: False)
    monkeypatch.setattr(embed_mod, "_embed_ollama", ollama_down)
    monkeypatch.setattr(embed_mod, "_embed_openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(RuntimeError):
        outcome_svc.scan(data_dir, projects)

    assert sent == []
    assert _rows(data_dir, "session") == []


# ---------------------------------------------------------------------------
# Robustness: damaged outcomes.jsonl, opt-out
# ---------------------------------------------------------------------------

_BAD_ROWS: list[dict[str, Any]] = [
    {**_session_row("bad", NOW - DAY, ["a"]), "ts": "yesterday"},
    {**_session_row("bad", NOW - DAY, ["a"]), "ts": None},
    {**_session_row("bad", NOW - DAY, ["a"]), "injected": None},
    {**_session_row("bad", NOW - DAY, ["a"]), "lines_scanned": "many"},
    {**_correction_row("s0", NOW - DAY, "failed", "a"), "score": "high"},
    {**_correction_row("s0", NOW - DAY, "failed", "a"), "block_id": ["a"]},
    {**_correction_row("s0", NOW - DAY, "miss", "a"), "ts": "noon"},
    {**_correction_row("s0", NOW - DAY, "failed", "a"), "injected": "yes"},
    {**_session_row("bad", NOW - DAY, ["a"]), "noise_n": "lots"},
    {"kind": "mystery", "session": "s0", "ts": NOW - DAY},
]


@pytest.mark.parametrize("bad", _BAD_ROWS)
def test_summarize_ignores_malformed_rows(data_dir: Path, bad: dict[str, Any]) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, ["a"]) for i in range(10)]
    _write_rows(data_dir, [*rows, bad])

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["sessions"] == 10
    assert stats["failed"] == []
    assert stats["missed"] == []


def test_summarize_survives_invalid_utf8(data_dir: Path) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, ["a"]) for i in range(10)]
    good = "".join(json.dumps(r) + "\n" for r in rows).encode("utf-8")
    (data_dir / outcome_svc.OUTCOMES_FILE).write_bytes(b"\xff\xfe\x00 torn\n" + good)

    assert outcome_svc.summarize(data_dir, now=NOW)["sessions"] == 10


def test_scan_after_torn_write_keeps_the_next_rows_readable(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())
    outcomes = data_dir / outcome_svc.OUTCOMES_FILE
    outcomes.write_text('{"kind": "session", "session": "torn", "ts": 1', encoding="utf-8")

    assert outcome_svc.scan(data_dir, projects) == 1

    readable = outcome_svc._read_rows(outcomes)
    assert [r["kind"] for r in readable] == ["correction", "session"]


def test_scan_is_skipped_when_turned_off_in_config(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    write_transcript(projects, "s1", _corrected_session())
    (data_dir / "config.yaml").write_text("outcome_scan: false\n", encoding="utf-8")

    assert outcome_svc.scan(data_dir, projects) == 0
    assert not (data_dir / outcome_svc.OUTCOMES_FILE).exists()


# ---------------------------------------------------------------------------
# Self-calibrated match threshold
# ---------------------------------------------------------------------------


def _noisy_session(name: str, n: int, mean: float, sd: float) -> dict[str, Any]:
    """A session row whose ordinary turns scored with the given mean and sd."""
    return {
        **_session_row(name, NOW - DAY, ["a"]),
        "noise_n": n,
        "noise_sum": n * mean,
        "noise_sumsq": n * (sd * sd + mean * mean),
    }


def test_threshold_falls_back_until_enough_ordinary_turns(data_dir: Path) -> None:
    _write_rows(data_dir, [_noisy_session("s0", 99, 0.5, 0.05)])

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["threshold"] == outcome_svc.DEFAULT_MATCH_THRESHOLD
    assert stats["noise_samples"] == 99


def test_threshold_is_noise_mean_plus_three_sd(data_dir: Path) -> None:
    rows = [_noisy_session(f"s{i}", 20, 0.5, 0.05) for i in range(10)]
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["threshold"] == 0.65
    assert stats["noise_samples"] == 200


def test_verdicts_follow_the_calibrated_threshold(data_dir: Path) -> None:
    """A score between the calibrated and the default threshold counts as a match."""
    rows = [_noisy_session(f"s{i}", 20, 0.5, 0.05) for i in range(10)]
    above = {**_correction_row("s0", NOW - DAY, "failed", "a"), "score": 0.68}
    below = {**_correction_row("s1", NOW - DAY, "failed", "a"), "score": 0.6}
    _write_rows(data_dir, [*rows, above, below])

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["failed"] == [{"block_id": "a", "count": 1}]
    assert stats["uncovered"] == 1


def test_scan_records_match_scores_of_ordinary_turns(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    projects = data_dir / "projects"
    path = write_transcript(
        projects,
        "s1",
        [
            user("set up the project", 0),
            assistant("Done.", 1),
            user("now add a test for the parser", 2),
            assistant("Added.", 3),
            user("log line " * 200, 4),
            assistant("Read it.", 5),
            user(RULE, 6),
        ],
    )

    outcome_svc.scan(data_dir, projects)
    (session,) = _rows(data_dir, "session")
    assert session["noise_n"] == 1
    assert 0.0 <= session["noise_sum"] < outcome_svc.DEFAULT_MATCH_THRESHOLD

    append_entries(path, [assistant("Fixed.", 7), user("show me the diff", 8)])
    outcome_svc.scan(data_dir, projects)
    assert _rows(data_dir, "session")[-1]["noise_n"] == 2


# ---------------------------------------------------------------------------
# Session-start load, recurrence, dormant blocks
# ---------------------------------------------------------------------------


def _new_row(session: str, ts: float, embedding: list[float]) -> dict[str, Any]:
    return {**_correction_row(session, ts, "new", None), "embedding": embedding}


def test_summarize_reports_sessions_with_priors_and_median_load(data_dir: Path) -> None:
    from turnzero.formatters import block_fmt
    from turnzero.services import retrieval_svc

    _write_block(data_dir, "venv-rule", [RULE])
    rows = [_session_row(f"with{i}", NOW - DAY, ["venv-rule"]) for i in range(4)]
    rows += [_session_row(f"none{i}", NOW - DAY, []) for i in range(6)]
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    size = block_fmt.injection_tokens(retrieval_svc._load_active_blocks()["venv-rule"])
    assert stats["sessions_injected"] == 4
    assert stats["median_load"] == size > 0


def test_summarize_load_ignores_blocks_no_longer_in_the_library(data_dir: Path) -> None:
    _write_block(data_dir, "venv-rule", [RULE])
    rows = [_session_row(f"s{i}", NOW - DAY, ["deleted-block"]) for i in range(10)]
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["sessions_injected"] == 10
    assert stats["median_load"] == 0


def test_summarize_counts_corrections_recurring_across_sessions(data_dir: Path) -> None:
    same = [1.0, 0.0, 0.0]
    other = [0.0, 1.0, 0.0]
    rows = [_session_row(f"s{i}", NOW - DAY, []) for i in range(10)]
    rows += [
        _new_row("s0", NOW - DAY, same),
        _new_row("s1", NOW - DAY, same),
        _new_row("s2", NOW - DAY, other),
        _new_row("s2", NOW - DAY, other),
    ]
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["recurring"] == 2


def test_summarize_recurring_survives_mixed_embedding_sizes(data_dir: Path) -> None:
    rows = [_session_row(f"s{i}", NOW - DAY, []) for i in range(10)]
    rows += [
        _new_row("s0", NOW - DAY, [1.0, 0.0, 0.0]),
        _new_row("s1", NOW - DAY, [1.0, 0.0, 0.0]),
        _new_row("s2", NOW - DAY, [1.0, 0.0]),
        {**_correction_row("s3", NOW - DAY, "new", None), "embedding": "not a vector"},
    ]
    _write_rows(data_dir, rows)

    assert outcome_svc.summarize(data_dir, now=NOW)["recurring"] == 2


def test_summarize_counts_dormant_own_blocks_and_data_days(data_dir: Path) -> None:
    _write_block(data_dir, "used-rule", [RULE])
    _write_block(data_dir, "unused-rule", ["always write tests first"])
    rows = [_session_row(f"s{i}", NOW - DAY, ["used-rule"]) for i in range(9)]
    rows.append(_session_row("oldest", NOW - 20 * DAY, []))
    _write_rows(data_dir, rows)

    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["own_blocks"] == 2
    assert stats["dormant"] == 1
    assert stats["data_days"] == 20


def test_summarize_new_numbers_without_data(data_dir: Path) -> None:
    stats = outcome_svc.summarize(data_dir, now=NOW)

    assert stats["sessions_injected"] == 0
    assert stats["median_load"] == 0
    assert stats["recurring"] == 0
    assert stats["data_days"] == 0
