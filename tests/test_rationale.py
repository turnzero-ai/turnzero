"""Tests for Rationale Enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from turnzero.blocks import Block, load_block


def test_load_block_fails_without_rationale(tmp_path: Path):
    block_path = tmp_path / "test-block.yaml"
    data = {
        "slug": "test-block",
        "version": "1.0.0",
        "intent": "build",
        "last_verified": "2026-04-28",
        "anti_patterns": ["Do not do X"]
    }
    block_path.write_text(yaml.dump(data))
    
    with pytest.raises(ValueError, match="missing a 'rationale'"):
        load_block(block_path)

def test_load_block_succeeds_with_rationale(tmp_path: Path):
    block_path = tmp_path / "test-block.yaml"
    data = {
        "slug": "test-block",
        "version": "1.0.0",
        "intent": "build",
        "last_verified": "2026-04-28",
        "anti_patterns": ["Do not do X"],
        "rationale": "Because Y"
    }
    block_path.write_text(yaml.dump(data))
    
    block = load_block(block_path)
    assert block.rationale == "Because Y"

def test_injection_text_includes_rationale():
    block = Block(
        slug="test-block",
        hash="hash",
        version="1.0.0",
        domain="python",
        intent="build",
        last_verified="2026-04-28",
        tags=[],
        context_weight=100,
        constraints=["Do X"],
        anti_patterns=["Do not do Y"],
        doc_anchors=[],
        rationale="Research shows Y causes Z."
    )
    
    text = block.to_injection_text()
    assert "# RATIONALE" in text
    assert "Research shows Y causes Z." in text
