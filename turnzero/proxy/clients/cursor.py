"""Cursor setup — detect installation, print pre-filled proxy instructions."""

from __future__ import annotations

import platform
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

_console = Console()


def _app_support_path() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor"
    if platform.system() == "Windows":
        import os
        return Path(os.environ.get("APPDATA", "")) / "Cursor"
    return Path.home() / ".config" / "Cursor"


def is_installed() -> bool:
    return _app_support_path().exists()


def print_instructions(port: int, secret: str) -> None:
    """Print pre-filled Cursor setup instructions to stderr."""
    url = f"http://localhost:{port}/v1"
    body = (
        "[bold]Cursor[/bold] stores model config in its UI — patch requires a manual step.\n\n"
        "  [dim]Settings → Models → Add Custom Model[/dim]\n\n"
        f"  [cyan]Base URL:[/cyan]  {url}\n"
        f"  [cyan]API Key:[/cyan]   <your provider key (Gemini / OpenAI / xAI)>\n"
        f"  [cyan]Header:[/cyan]    X-TurnZero-Secret: {secret}\n\n"
        "TurnZero injects your Expert Priors before every Turn 0 request."
    )
    _console.print(
        Panel(body, title="[bold yellow]Cursor Setup[/bold yellow]", border_style="yellow"),
        highlight=False,
    )
