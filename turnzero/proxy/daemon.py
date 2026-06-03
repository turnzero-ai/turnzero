"""Daemon management — install/uninstall/status for launchd (macOS) and systemd (Linux)."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from turnzero.config import get_data_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLIST_LABEL = "ai.turnzero.proxy"

_LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"
_SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"

_PLIST_FILENAME = f"{PLIST_LABEL}.plist"
_UNIT_FILENAME = "turnzero-proxy.service"


def _plist_path() -> Path:
    return _LAUNCHD_DIR / _PLIST_FILENAME


def _unit_path() -> Path:
    return _SYSTEMD_DIR / _UNIT_FILENAME


# ---------------------------------------------------------------------------
# Executable resolution
# ---------------------------------------------------------------------------


def _resolve_executable() -> Path:
    """Return path to the turnzero CLI executable."""
    candidate = Path(sys.executable).parent / "turnzero"
    if candidate.exists():
        return candidate
    # Fallback: search PATH
    which = subprocess.run(["which", "turnzero"], capture_output=True, text=True, check=False)
    if which.returncode == 0:
        return Path(which.stdout.strip())
    raise RuntimeError(
        "Cannot locate turnzero executable. "
        "Ensure TurnZero is installed and the venv is active."
    )


# ---------------------------------------------------------------------------
# macOS launchd
# ---------------------------------------------------------------------------


def generate_plist(executable: Path, secret: str, port: int, data_dir: Path) -> str:
    """Return launchd plist XML for the proxy daemon."""
    log = data_dir / "proxy.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
        <string>proxy</string>
        <string>serve</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TURNZERO_DATA_DIR</key>
        <string>{data_dir}</string>
        <key>TURNZERO_PROXY_SECRET</key>
        <string>{secret}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""


def _launchctl(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def _install_macos(secret: str, port: int) -> None:
    exe = _resolve_executable()
    data_dir = get_data_dir()
    plist = generate_plist(exe, secret, port, data_dir)

    _LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)
    p = _plist_path()
    p.write_text(plist)

    # Unload first (idempotent — ignore errors)
    _launchctl(["unload", str(p)])
    rc, out = _launchctl(["load", str(p)])
    if rc != 0:
        raise RuntimeError(f"launchctl load failed: {out.strip()}")


def _uninstall_macos() -> None:
    p = _plist_path()
    if p.exists():
        _launchctl(["unload", str(p)])
        p.unlink()


def _status_macos() -> bool:
    """Return True if daemon is loaded and has a PID."""
    rc, out = _launchctl(["list", PLIST_LABEL])
    return rc == 0 and '"PID"' in out


# ---------------------------------------------------------------------------
# Linux systemd
# ---------------------------------------------------------------------------


def generate_unit(executable: Path, secret: str, port: int, data_dir: Path) -> str:
    """Return systemd user service unit file content."""
    log = data_dir / "proxy.log"
    return f"""[Unit]
Description=TurnZero Proxy
After=network.target

[Service]
ExecStart={executable} proxy serve --port {port}
Environment=TURNZERO_DATA_DIR={data_dir}
Environment=TURNZERO_PROXY_SECRET={secret}
Restart=always
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""


def _systemctl(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout + result.stderr


def _install_linux(secret: str, port: int) -> None:
    exe = _resolve_executable()
    data_dir = get_data_dir()
    unit = generate_unit(exe, secret, port, data_dir)

    _SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    _unit_path().write_text(unit)

    _systemctl(["daemon-reload"])
    rc, out = _systemctl(["enable", "--now", _UNIT_FILENAME])
    if rc != 0:
        raise RuntimeError(f"systemctl enable failed: {out.strip()}")


def _uninstall_linux() -> None:
    _systemctl(["disable", "--now", _UNIT_FILENAME])
    p = _unit_path()
    if p.exists():
        p.unlink()
    _systemctl(["daemon-reload"])


def _status_linux() -> bool:
    rc, _ = _systemctl(["is-active", _UNIT_FILENAME])
    return rc == 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install(secret: str, port: int) -> None:
    """Install and start the proxy daemon for the current platform."""
    system = platform.system()
    if system == "Darwin":
        _install_macos(secret, port)
    elif system == "Linux":
        _install_linux(secret, port)
    else:
        raise RuntimeError(f"Daemon install not supported on {system}.")


def uninstall() -> None:
    """Stop and remove the proxy daemon."""
    system = platform.system()
    if system == "Darwin":
        _uninstall_macos()
    elif system == "Linux":
        _uninstall_linux()
    else:
        raise RuntimeError(f"Daemon uninstall not supported on {system}.")


def status() -> bool:
    """Return True if the daemon is running."""
    system = platform.system()
    if system == "Darwin":
        return _status_macos()
    if system == "Linux":
        return _status_linux()
    return False


def installed_path() -> Path | None:
    """Return path to the installed daemon config file, or None if not installed."""
    system = platform.system()
    if system == "Darwin":
        p = _plist_path()
        return p if p.exists() else None
    if system == "Linux":
        p = _unit_path()
        return p if p.exists() else None
    return None


def config_for_display() -> dict[str, Any]:
    """Return daemon config dict for status display (reads installed file)."""
    p = installed_path()
    if p is None:
        return {}
    return {"path": str(p), "platform": platform.system()}
