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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (tmp_path / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True, "local": True}})
    )
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {
        "k8s-build": _make_block("k8s-build", "kubernetes"),
    })

    with pytest.raises(ValueError, match="not in active domains"):
        retrieval_svc.inject_block("k8s-build")


def test_inject_block_personal_tier_always_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (tmp_path / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"personal": True}})
    )
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    personal_block = _make_block("my-pref", "global", tier="personal")
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {"my-pref": personal_block})
    monkeypatch.setattr(retrieval_svc, "record_session_injection", lambda *a: None)
    monkeypatch.setattr(retrieval_svc, "record_project_affinity", lambda *a: None)
    import turnzero.telemetry as tel
    monkeypatch.setattr(tel, "track_block_injected", lambda **kw: None)

    result = retrieval_svc.inject_block("my-pref")
    assert result  # no raise, returns formatted text


def test_get_block_reports_inactive_when_domain_not_in_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (tmp_path / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True}})
    )
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {
        "k8s-build": _make_block("k8s-build", "kubernetes"),
    })

    result = retrieval_svc.get_block("k8s-build")
    assert result["active"] is False
    assert result["slug"] == "k8s-build"  # content still returned


def test_get_block_active_true_when_domain_in_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from turnzero.services import retrieval_svc

    (tmp_path / "config.yaml").write_text(
        yaml.dump({"active_domains": ["python"], "sources": {"community": True}})
    )
    monkeypatch.setenv("TURNZERO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(retrieval_svc, "_load_active_blocks", lambda: {
        "py-build": _make_block("py-build", "python"),
    })

    result = retrieval_svc.get_block("py-build")
    assert result["active"] is True
