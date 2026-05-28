"""Unit tests for the retrieval service layer."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from turnzero.blocks import Block
from turnzero.services import retrieval_svc


@pytest.fixture
def mock_blocks_1() -> dict[str, Block]:
    return {
        "test-block-1": Block(
            slug="test-block-1",
            hash="hash1",
            version="1.0.0",
            domain="test",
            intent="build",
            last_verified="2026-01-01",
            tags=[],
            context_weight=100,
            constraints=["Constraint 1"],
            anti_patterns=[],
            doc_anchors=[],
            tier="local",
        )
    }


@pytest.fixture
def mock_blocks_2() -> dict[str, Block]:
    return {
        "test-block-1": Block(
            slug="test-block-1",
            hash="hash2",  # Different hash to distinguish from mock_blocks_1
            version="1.0.1",
            domain="test",
            intent="build",
            last_verified="2026-01-02",
            tags=[],
            context_weight=100,
            constraints=["Constraint 1 Updated"],
            anti_patterns=[],
            doc_anchors=[],
            tier="local",
        )
    }


def test_block_cache_invalidation(
    tmp_path: Path, mock_blocks_1: dict[str, Block], mock_blocks_2: dict[str, Block]
) -> None:
    """Verify that the block cache invalidates when a file mtime changes."""
    blocks_dir = tmp_path / "blocks"
    local_dir = blocks_dir / "local" / "test"
    local_dir.mkdir(parents=True)
    block_file = local_dir / "test-block-1.yaml"
    block_file.write_text(
        "slug: test-block-1\nversion: 1.0.0\nintent: build\nlast_verified: '2026-01-01'",
        encoding="utf-8",
    )

    # Clear cache before starting
    retrieval_svc._BLOCKS_CACHE.clear()

    with (
        patch(
            "turnzero.services.retrieval_svc.get_blocks_dir", return_value=blocks_dir
        ),
        patch(
            "turnzero.services.retrieval_svc.enabled_sources", return_value=["local"]
        ),
        patch("turnzero.services.retrieval_svc.load_all_blocks") as mock_load,
    ):
        # Setup mock to return different data on successive calls
        mock_load.side_effect = [mock_blocks_1, mock_blocks_2]

        # First load - should hit disk
        blocks1 = retrieval_svc._load_active_blocks()
        assert blocks1["test-block-1"].hash == "hash1"
        assert mock_load.call_count == 1

        # Second load - should hit cache
        blocks2 = retrieval_svc._load_active_blocks()
        assert blocks2["test-block-1"].hash == "hash1"
        assert blocks2 is blocks1
        assert mock_load.call_count == 1

        # Modify mtime - should invalidate and hit disk
        new_mtime = time.time() + 100
        os.utime(block_file, (new_mtime, new_mtime))

        blocks3 = retrieval_svc._load_active_blocks()
        assert mock_load.call_count == 2
        assert blocks3["test-block-1"].hash == "hash2"
        assert blocks3 is not blocks1


# ---------------------------------------------------------------------------
# FIX-1: active_domains filter consistency
# ---------------------------------------------------------------------------


def _make_block(slug: str, domain: str, tier: str = "community") -> Block:
    from turnzero.blocks import Block
    return Block(
        slug=slug, hash="h", version="1.0.0", domain=domain, intent="build",
        last_verified="2026-01-01", tags=[], context_weight=100,
        constraints=["Do the thing"], anti_patterns=[], doc_anchors=[],
        conflicts_with=[], conflicts_with_tags=[], provides=[], requires=[],
        confidence=1.0, verification_level="curated", rationale=None,
        archived=False, tier=tier,
    )


def test_inject_block_raises_when_domain_inactive(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True, "local": True}})
    )
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {
        "k8s-build": _make_block("k8s-build", "kubernetes"),
    })

    with pytest.raises(ValueError, match="not in active domains"):
        retrieval_svc.inject_block("k8s-build")


def test_inject_block_personal_tier_always_passes(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"personal": True}})
    )
    personal_block = _make_block("my-pref", "global", tier="personal")
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {"my-pref": personal_block})
    monkeypatch.setattr(retrieval_svc, "record_session_injection", lambda *a: None)
    monkeypatch.setattr(retrieval_svc, "record_project_affinity", lambda *a: None)
    import turnzero.telemetry as tel
    monkeypatch.setattr(tel, "track_block_injected", lambda **kw: None)

    result = retrieval_svc.inject_block("my-pref")
    assert result  # no raise, returns formatted text


def test_get_block_reports_inactive_when_domain_not_in_active(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True}})
    )
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {
        "k8s-build": _make_block("k8s-build", "kubernetes"),
    })

    result = retrieval_svc.get_block("k8s-build")
    assert result["active"] is False
    assert result["slug"] == "k8s-build"  # content still returned


def test_get_block_active_true_when_domain_in_active(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True}})
    )
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {
        "py-build": _make_block("py-build", "python"),
    })

    result = retrieval_svc.get_block("py-build")
    assert result["active"] is True


def test_list_suggested_blocks_filters_inactive_domain(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """active_domains set → blocks from inactive domain excluded before query."""
    import yaml

    import turnzero.retrieval as ret
    import turnzero.services.retrieval_svc as rsvc
    import turnzero.services.stats_svc as ssvc
    import turnzero.telemetry as tel

    (data_dir / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True}})
    )
    monkeypatch.setattr(rsvc, "_load_active_blocks", lambda: {
        "py-build": _make_block("py-build", "python"),
        "k8s-build": _make_block("k8s-build", "kubernetes"),
    })
    captured_blocks: list[str] = []

    def _fake_query(prompt: str, index: list, blocks: dict, **kw: object) -> list:
        captured_blocks.extend(blocks.keys())
        return []

    monkeypatch.setattr(rsvc, "_query", _fake_query)
    monkeypatch.setattr(rsvc, "_load_active_index", lambda: [])
    monkeypatch.setattr(rsvc, "get_session_injections", lambda _: set())
    monkeypatch.setattr(ret, "get_identity_context", lambda blocks, **kw: ([], False))
    monkeypatch.setattr(ssvc, "log_injection", lambda **kw: None)
    monkeypatch.setattr(tel, "track_session_start", lambda **kw: None)

    rsvc.list_suggested_blocks("build something in python", session_id=None)

    assert "py-build" in captured_blocks
    assert "k8s-build" not in captured_blocks


# ---------------------------------------------------------------------------
# UX-1: "no priors matched" hint — logic lives in retrieval_svc (MCP-1)
# ---------------------------------------------------------------------------

def _patch_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch retrieval_svc internals so list_suggested_blocks returns no blocks."""
    import turnzero.retrieval as ret
    import turnzero.services.retrieval_svc as rsvc
    import turnzero.services.stats_svc as ssvc
    import turnzero.telemetry as tel

    monkeypatch.setattr(rsvc, "_load_active_blocks", lambda: {})
    monkeypatch.setattr(rsvc, "_load_active_index", lambda: [])
    monkeypatch.setattr(rsvc, "_query", lambda *a, **kw: [])
    monkeypatch.setattr(rsvc, "get_session_injections", lambda _: set())
    monkeypatch.setattr(ret, "get_identity_context", lambda blocks, **kw: ([], False))
    monkeypatch.setattr(ssvc, "log_injection", lambda **kw: None)
    monkeypatch.setattr(tel, "track_session_start", lambda **kw: None)


def test_no_match_hint_fires_when_gate_passes_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Impl gate passes but no blocks match → hint entry appended by retrieval_svc."""
    import turnzero.services.retrieval_svc as rsvc

    _patch_empty_results(monkeypatch)
    monkeypatch.setattr(rsvc, "is_implementation_prompt", lambda *a, **kw: True)

    results = rsvc.list_suggested_blocks("write a kubernetes deployment manifest")
    hint = [r for r in results if r.get("block_id") == "no-match-hint"]
    assert hint, "hint entry missing when gate passes and results empty"
    assert "turnzero query" in hint[0]["preview"]


def test_no_match_hint_suppressed_for_chitchat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chitchat → gate fails → no hint even when results empty."""
    import turnzero.services.retrieval_svc as rsvc

    _patch_empty_results(monkeypatch)
    monkeypatch.setattr(rsvc, "is_implementation_prompt", lambda *a, **kw: False)

    results = rsvc.list_suggested_blocks("thanks looks good")
    hint = [r for r in results if r.get("block_id") == "no-match-hint"]
    assert not hint, "hint must not fire for chitchat"


def test_no_match_hint_suppressed_when_results_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-empty results → hint not appended."""
    import turnzero.retrieval as ret
    import turnzero.services.retrieval_svc as rsvc
    import turnzero.services.stats_svc as ssvc
    import turnzero.telemetry as tel

    fake_block = _make_block("py-build", "python")
    monkeypatch.setattr(rsvc, "_load_active_blocks", lambda: {"py-build": fake_block})
    monkeypatch.setattr(rsvc, "_load_active_index", lambda: [])
    monkeypatch.setattr(rsvc, "_query", lambda *a, **kw: [(fake_block, 0.85)])
    monkeypatch.setattr(rsvc, "get_session_injections", lambda _: set())
    monkeypatch.setattr(ret, "get_identity_context", lambda blocks, **kw: ([], False))
    monkeypatch.setattr(ssvc, "log_injection", lambda **kw: None)
    monkeypatch.setattr(tel, "track_session_start", lambda **kw: None)

    results = rsvc.list_suggested_blocks("write a python script")
    hint = [r for r in results if r.get("block_id") == "no-match-hint"]
    assert not hint
