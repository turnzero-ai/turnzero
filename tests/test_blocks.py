"""Tests for block loading, validation, and formatting."""

from pathlib import Path

import pytest

from turnzero.blocks import Block, DocAnchor, load_all_blocks, load_block

BLOCKS_DIR = Path("data/blocks")

VALID_INTENTS = {"build", "debug", "migrate", "review"}


@pytest.fixture(scope="module")
def all_blocks() -> dict[str, Block]:
    return load_all_blocks(BLOCKS_DIR)


def test_load_all_blocks_finds_seed_files(all_blocks: dict[str, Block]) -> None:
    assert len(all_blocks) >= 8, "Expected at least 8 seed blocks"


def test_all_blocks_have_required_fields(all_blocks: dict[str, Block]) -> None:
    for block_id, block in all_blocks.items():
        assert block.id, f"{block_id}: missing id"
        assert block.version, f"{block_id}: missing version"
        assert block.domain, f"{block_id}: missing domain"
        assert block.intent in VALID_INTENTS, f"{block_id}: invalid intent '{block.intent}'"
        assert block.context_weight > 0, f"{block_id}: context_weight must be > 0"


def test_all_blocks_have_content(all_blocks: dict[str, Block]) -> None:
    for block_id, block in all_blocks.items():
        assert len(block.constraints) > 0, f"{block_id}: no constraints"
        assert len(block.anti_patterns) > 0, f"{block_id}: no anti_patterns"


def test_seed_blocks_not_stale(all_blocks: dict[str, Block]) -> None:
    # All seed blocks verified today should pass the 90-day check
    for block_id, block in all_blocks.items():
        assert not block.is_stale(), f"{block_id}: marked stale (last_verified={block.last_verified})"


def test_search_text_contains_domain(all_blocks: dict[str, Block]) -> None:
    for block_id, block in all_blocks.items():
        text = block.to_search_text()
        assert block.domain in text, f"{block_id}: domain missing from search text"
        assert len(text) > 10, f"{block_id}: search text too short"


def test_injection_text_has_sections(all_blocks: dict[str, Block]) -> None:
    for block_id, block in all_blocks.items():
        text = block.to_injection_text()
        assert "# EXPERT_PRIOR_IDENTITY" in text, f"{block_id}: missing Identity section"
        assert "# SESSION_CONSTRAINTS" in text, f"{block_id}: missing Constraints section"
        assert "# ANTI_PATTERNS" in text, f"{block_id}: missing Anti-patterns section"
        assert "# VALIDATION_TASK" in text, f"{block_id}: missing Task section"
        assert block.id in text, f"{block_id}: block id missing from injection text"


def test_load_single_block_roundtrip() -> None:
    path = BLOCKS_DIR / "community" / "nextjs" / "nextjs15-approuter-build.yaml"
    block = load_block(path)
    assert block.domain == "nextjs"
    assert block.intent == "build"
    assert len(block.constraints) > 0
    assert len(block.doc_anchors) > 0
    assert isinstance(block.doc_anchors[0], DocAnchor)


def test_is_stale_boundary() -> None:
    from datetime import date, timedelta

    old_date = (date.today() - timedelta(days=91)).isoformat()
    recent_date = (date.today() - timedelta(days=10)).isoformat()

    stale_block = Block(
        slug="test", hash="abc", version="1.0.0", domain="test", intent="build",
        last_verified=old_date, tags=[], context_weight=100,
        constraints=[], anti_patterns=[], doc_anchors=[],
    )
    fresh_block = Block(
        slug="test", hash="abc", version="1.0.0", domain="test", intent="build",
        last_verified=recent_date, tags=[], context_weight=100,
        constraints=[], anti_patterns=[], doc_anchors=[],
    )

    assert stale_block.is_stale()
    assert not fresh_block.is_stale()
