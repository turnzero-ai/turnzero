"""Tests for ConfigManager (REF-4) and stats_svc.compute_display_data (REF-2)."""

from __future__ import annotations

import json
import time
from pathlib import Path

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
        "est_turns",
        "est_tokens",
        "blocks_total",
        "data_dir",
    ):
        assert key in data, f"Missing key: {key}"


def test_compute_display_data_uses_roi_constants(tmp_path: Path) -> None:
    """est_turns and est_tokens must derive from analytics constants, not magic literals."""
    from turnzero.analytics import TOKENS_PER_TURN, TURNS_SAVED_PER_INJECTION
    from turnzero.services import stats_svc

    # Write a fake hook_log with 10 block injections
    log = tmp_path / "hook_log.jsonl"
    log.write_text(
        json.dumps(
            {"ts": time.time(), "blocks": ["b1"] * 10, "domains": ["python"], "tokens_injected": 0}
        )
        + "\n"
    )

    data = stats_svc.compute_display_data(tmp_path)
    assert data["est_turns"] == round(10 * TURNS_SAVED_PER_INJECTION)
    assert data["est_tokens"] == 10 * TURNS_SAVED_PER_INJECTION * TOKENS_PER_TURN
