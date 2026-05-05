"""PyPI upgrade check — cached, non-blocking, silent on failure."""

from __future__ import annotations

import json
import time
from pathlib import Path

_PYPI_URL = "https://pypi.org/pypi/turnzero/json"
_CHECK_INTERVAL_SECONDS = 86_400  # 24 h


def _installed_version() -> str:
    try:
        from importlib.metadata import version

        return version("turnzero")
    except Exception:
        return "unknown"


def _is_newer(latest: str, current: str) -> bool:
    try:

        def _parts(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split(".")[:3])

        return _parts(latest) > _parts(current)
    except Exception:
        return False


def check_for_upgrade(data_dir: Path) -> tuple[str | None, bool]:
    """Return (latest_version, is_newer). Returns (None, False) on any failure.

    Result cached in data_dir/upgrade_check.json for 24 h.
    Always silent on network errors.
    """
    try:
        current = _installed_version()
        if current == "unknown":
            return None, False

        cache_path = data_dir / "upgrade_check.json"

        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < _CHECK_INTERVAL_SECONDS:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                latest = cached.get("latest", "")
                if latest:
                    return latest, _is_newer(latest, current)

        import httpx

        resp = httpx.get(_PYPI_URL, timeout=3.0)
        resp.raise_for_status()
        latest = resp.json()["info"]["version"]
        cache_path.write_text(
            json.dumps({"latest": latest, "checked_at": time.time()}),
            encoding="utf-8",
        )
        return latest, _is_newer(latest, current)

    except Exception:
        return None, False
