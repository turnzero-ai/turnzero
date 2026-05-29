"""Tests for Setup Upgrade Safety and Harvest Opt-in."""

import contextlib
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from turnzero.cli.review import harvest
from turnzero.cli.setup import setup


def test_setup_merges_blocks_instead_of_overwriting(tmp_path: Path):
    """setup should merge blocks into existing tiers, preserving user-added files."""
    dest_dir = tmp_path / "dest"
    source_dir = tmp_path / "source"

    # Existing user blocks in destination
    dest_tier = dest_dir / "blocks" / "community" / "python"
    dest_tier.mkdir(parents=True)
    user_block = dest_tier / "user-custom.yaml"
    user_block.write_text("slug: user-custom\n")

    # Source blocks to sync
    source_tier = source_dir / "blocks" / "community" / "python"
    source_tier.mkdir(parents=True)
    community_block = source_tier / "community-std.yaml"
    community_block.write_text("slug: community-std\n")

    # Mocking necessary parts for setup()
    mock_file = str(source_dir / "turnzero" / "cli" / "setup.py")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("turnzero.cli.setup.Path.home", return_value=tmp_path),
        patch("turnzero.cli.setup.__file__", mock_file),
        patch("shutil.which", return_value=None),
        patch(
            "turnzero.config.get_bundled_index_path",
            return_value=tmp_path / "nonexistent",
        ),
        patch("turnzero.cli.setup.console", MagicMock()),
    ):
        pkg_blocks = source_dir / "turnzero" / "data" / "blocks"
        pkg_blocks.mkdir(parents=True)
        shutil.copytree(source_dir / "blocks", pkg_blocks, dirs_exist_ok=True)

        # Provide explicit values for all typer options when calling directly
        setup(
            data_dir=dest_dir,
            force=True,
            interactive=False,
            openai_key=None,
        )

    # Verify both blocks exist
    assert (dest_tier / "user-custom.yaml").exists()
    assert (dest_tier / "community-std.yaml").exists()


def test_harvest_all_prompts_for_opt_in(tmp_path: Path):
    """harvest --all should prompt for opt-in on first run and save preference."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with (
        patch("turnzero.cli.review.get_data_dir", return_value=data_dir),
        patch("turnzero.cli.review.console", MagicMock()),
        patch("turnzero.cli.review.typer.confirm", return_value=True) as mock_confirm,
        patch("turnzero.harvest.scan_new_sessions", return_value=[]),
        patch("turnzero.config.save_config") as mock_save_cfg,
    ):
        # Run harvest --all
        with contextlib.suppress(SystemExit):
            harvest(all_new=True)

        assert mock_confirm.called

        args, _ = mock_save_cfg.call_args
        assert args[1]["harvest_opt_in"] is True


def test_harvest_all_skips_prompt_if_already_opted_in(tmp_path: Path):
    """harvest --all should not prompt if harvest_opt_in is already True."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    from turnzero.config import load_config, save_config

    cfg = load_config(data_dir)
    cfg["harvest_opt_in"] = True
    save_config(data_dir, cfg)

    with (
        patch("turnzero.cli.review.get_data_dir", return_value=data_dir),
        patch("turnzero.cli.review.console", MagicMock()),
        patch("turnzero.cli.review.typer.confirm") as mock_confirm,
        patch("turnzero.harvest.scan_new_sessions", return_value=[]),
    ):
        harvest(all_new=True)

        assert not mock_confirm.called
