"""Tests for turnzero/proxy/daemon.py — plist/unit generation and install/uninstall."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from turnzero.proxy.daemon import (
    PLIST_LABEL,
    generate_plist,
    generate_unit,
    installed_path,
)

_EXE = Path("/usr/local/bin/turnzero")
_SECRET = "test-secret-abc"
_PORT = 9981
_DATA_DIR = Path("/tmp/tz_test")


# ---------------------------------------------------------------------------
# generate_plist
# ---------------------------------------------------------------------------


def test_generate_plist_contains_label() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert PLIST_LABEL in xml


def test_generate_plist_embeds_secret_in_args() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert _SECRET in xml


def test_generate_plist_embeds_port_in_args() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert str(_PORT) in xml


def test_generate_plist_embeds_data_dir_as_env() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert str(_DATA_DIR) in xml
    assert "TURNZERO_DATA_DIR" in xml


def test_generate_plist_sets_run_at_load() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert "RunAtLoad" in xml
    assert "<true/>" in xml


def test_generate_plist_sets_keep_alive() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert "KeepAlive" in xml


def test_plist_is_valid_xml() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    ET.fromstring(xml)  # raises if invalid


def test_plist_contains_log_path() -> None:
    xml = generate_plist(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert "proxy.log" in xml


# ---------------------------------------------------------------------------
# generate_unit (Linux systemd)
# ---------------------------------------------------------------------------


def test_generate_unit_contains_exec_start() -> None:
    unit = generate_unit(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert "ExecStart" in unit
    assert str(_EXE) in unit


def test_generate_unit_embeds_secret() -> None:
    unit = generate_unit(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert _SECRET in unit


def test_generate_unit_sets_restart_always() -> None:
    unit = generate_unit(_EXE, _SECRET, _PORT, _DATA_DIR)
    assert "Restart=always" in unit


# ---------------------------------------------------------------------------
# installed_path
# ---------------------------------------------------------------------------


def test_installed_path_returns_none_when_absent(tmp_path: Path) -> None:
    with (
        patch("turnzero.proxy.daemon._plist_path", return_value=tmp_path / "absent.plist"),
        patch("turnzero.proxy.daemon._unit_path", return_value=tmp_path / "absent.service"),
        patch("turnzero.proxy.daemon.platform.system", return_value="Darwin"),
    ):
        assert installed_path() is None


def test_installed_path_returns_path_when_present(tmp_path: Path) -> None:
    plist = tmp_path / f"{PLIST_LABEL}.plist"
    plist.write_text("<plist/>")
    with (
        patch("turnzero.proxy.daemon._plist_path", return_value=plist),
        patch("turnzero.proxy.daemon.platform.system", return_value="Darwin"),
    ):
        assert installed_path() == plist


# ---------------------------------------------------------------------------
# install / uninstall (macOS, mocked subprocess)
# ---------------------------------------------------------------------------


def test_install_macos_writes_plist(tmp_path: Path) -> None:
    plist_file = tmp_path / f"{PLIST_LABEL}.plist"

    with (
        patch("turnzero.proxy.daemon._plist_path", return_value=plist_file),
        patch("turnzero.proxy.daemon._LAUNCHD_DIR", tmp_path),
        patch("turnzero.proxy.daemon._resolve_executable", return_value=_EXE),
        patch("turnzero.proxy.daemon.get_data_dir", return_value=_DATA_DIR),
        patch("turnzero.proxy.daemon._launchctl", return_value=(0, "")),
    ):
        from turnzero.proxy.daemon import _install_macos
        _install_macos(secret=_SECRET, port=_PORT)

    assert plist_file.exists()
    assert _SECRET in plist_file.read_text()


def test_uninstall_macos_removes_plist(tmp_path: Path) -> None:
    plist_file = tmp_path / f"{PLIST_LABEL}.plist"
    plist_file.write_text("<plist/>")

    with (
        patch("turnzero.proxy.daemon._plist_path", return_value=plist_file),
        patch("turnzero.proxy.daemon._launchctl", return_value=(0, "")),
    ):
        from turnzero.proxy.daemon import _uninstall_macos
        _uninstall_macos()

    assert not plist_file.exists()
