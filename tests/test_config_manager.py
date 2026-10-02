"""Tests for ConfigManager (REF-4) and stats_svc.compute_display_data (REF-2)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from turnzero.config import ConfigManager, _deep_merge


def test_deep_merge_scalar_override(tmp_path: Path) -> None:
    base = {"key": "old", "other": 1}
    result = _deep_merge(base, {"key": "new"})
    assert result["key"] == "new"
    assert result["other"] == 1


def test_deep_merge_dict_nested(tmp_path: Path) -> None:
    base = {"sources": {"local": True, "community": False}}
    result = _deep_merge(base, {"sources": {"community": True}})
    assert result["sources"]["local"] is True
    assert result["sources"]["community"] is True


def test_deep_merge_does_not_mutate_base() -> None:
    base = {"key": "original"}
    _deep_merge(base, {"key": "changed"})
    assert base["key"] == "original"


def test_config_manager_load_defaults_when_no_file(tmp_path: Path) -> None:
    defaults = {"foo": "bar", "count": 0}
    mgr = ConfigManager("settings", tmp_path, defaults)
    cfg = mgr.load()
    assert cfg["foo"] == "bar"
    assert cfg["count"] == 0


def test_config_manager_save_and_load(tmp_path: Path) -> None:
    defaults = {"sources": {"local": True}, "flag": False}
    mgr = ConfigManager("settings", tmp_path, defaults)
    mgr.save({"sources": {"local": True, "community": True}, "flag": True})
    cfg = mgr.load()
    assert cfg["flag"] is True
    assert cfg["sources"]["community"] is True


def test_config_manager_sections_isolated(tmp_path: Path) -> None:
    """Saving one config section must not affect another."""
    a = ConfigManager("config", tmp_path, {"x": 1})
    b = ConfigManager("telemetry", tmp_path, {"y": 2})

    a.save({"x": 99})
    assert b.load()["y"] == 2  # telemetry untouched


def test_compute_display_data_returns_expected_keys(tmp_path: Path) -> None:
    from turnzero.services import stats_svc

    data = stats_svc.compute_display_data(tmp_path)
    for key in (
        "sessions_total",
        "priors_total",
        "corrections_total",
        "outcomes",
        "blocks_total",
        "data_dir",
    ):
        assert key in data, f"Missing key: {key}"


def test_compute_display_data_has_no_estimates(tmp_path: Path) -> None:
    """Stats report measured outcomes; constant-based estimates are gone."""
    from turnzero.services import stats_svc

    log = tmp_path / "hook_log.jsonl"
    log.write_text(
        json.dumps(
            {"ts": time.time(), "blocks": ["b1"] * 10, "domains": ["python"], "tokens_injected": 0}
        )
        + "\n"
    )

    data = stats_svc.compute_display_data(tmp_path)
    assert "est_turns" not in data
    assert "est_tokens" not in data
    assert data["outcomes"]["repeat_rate"] is None


# ── DEBT-6: compute() data_dir param + no env-var mutation ───────────────────

def test_compute_with_explicit_data_dir(tmp_path: Path) -> None:
    """compute(data_dir=...) reads from the supplied dir, not get_data_dir()."""
    import json
    import time

    from turnzero.services import stats_svc

    # Write 3 injection entries to tmp_path only
    log = tmp_path / "hook_log.jsonl"
    log.write_text(
        "\n".join(
            json.dumps({"ts": time.time(), "blocks": ["b1"], "domains": ["python"], "tokens_injected": 0})
            for _ in range(3)
        )
        + "\n"
    )

    data = stats_svc.compute(data_dir=tmp_path)
    assert data["sessions"]["total"] == 3
    assert data["priors_injected"]["total"] == 3


def test_compute_display_data_no_env_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compute_display_data() must not set or leave TURNZERO_DATA_DIR in the env."""

    from turnzero.services import stats_svc

    monkeypatch.delenv("TURNZERO_DATA_DIR", raising=False)

    stats_svc.compute_display_data(tmp_path)

    after_env = {k: v for k, v in os.environ.items() if k == "TURNZERO_DATA_DIR"}
    assert not after_env, "TURNZERO_DATA_DIR must not be set after compute_display_data()"


# ── TST-DEBT-2: the suite must never touch a real data directory ─────────────


def test_suite_never_uses_the_real_data_dir() -> None:
    """Without the data_dir fixture, tests still get a throwaway data directory."""
    from turnzero.config import get_data_dir

    resolved = get_data_dir().resolve()
    assert resolved != (Path.home() / ".turnzero").resolve()
    assert resolved != Path("data").resolve()


def test_logging_without_data_dir_fixture_stays_out_of_home() -> None:
    from turnzero.config import get_data_dir
    from turnzero.services import stats_svc

    real_log = Path.home() / ".turnzero" / "hook_log.jsonl"
    before = real_log.stat().st_size if real_log.exists() else None

    stats_svc.log_injection(["b1"], ["python"], 3)

    after = real_log.stat().st_size if real_log.exists() else None
    assert after == before
    assert (get_data_dir() / "hook_log.jsonl").exists()
