"""Diagnostic and verification commands."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import httpx
from rich.table import Table

from turnzero.cli.base import (
    _blocks_dir,
    _data_dir,
    _index_path,
    console,
)
from turnzero.mcp_server import _list_suggested_blocks

HTTP_OK = 200


def verify() -> None:
    """Run a full system diagnostic to confirm TurnZero is ready and correctly registered."""
    console.print("\n[bold]TurnZero Doctor — Diagnostic Report[/bold]\n")

    data_dir = _data_dir()

    # 1. Embedding Backend
    _verify_embeddings()

    # 2. Index & Library
    _verify_index_and_library(data_dir)

    # 3. Client Registration
    _verify_client_registrations(data_dir)

    # 4. Retrieval Probe
    _verify_retrieval_probe()

    console.print(
        "\n[dim]If any checks failed, run [cyan]turnzero setup --force[/cyan] to repair.[/dim]\n"
    )


def _verify_embeddings() -> None:
    console.print("[bold]1. Embedding Backend[/bold]")
    ollama_path = shutil.which("ollama")

    if ollama_path:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            with httpx.Client(timeout=1.0) as client:
                resp = client.get(f"{host}/api/tags")
                if resp.status_code == HTTP_OK:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    if (
                        "nomic-embed-text:latest" in models
                        or "nomic-embed-text" in models
                    ):
                        console.print(
                            "  [green]✓[/green] ollama is running with nomic-embed-text"
                        )
                    else:
                        console.print(
                            "  [yellow]⚠[/yellow] ollama is running but nomic-embed-text is missing"
                        )
                else:
                    console.print(
                        f"  [red]✗[/red] ollama server returned error: {resp.status_code}"
                    )
        except Exception:
            console.print(
                "  [red]✗[/red] ollama server is not reachable (check if it is running)"
            )
    elif os.environ.get("OPENAI_API_KEY") or (_data_dir() / "openai_key").exists():
        console.print("  [green]✓[/green] OpenAI API key is configured")
    else:
        console.print("  [red]✗[/red] No embedding backend found (ollama or OpenAI)")
    console.print()


def _verify_index_and_library(data_dir: Path) -> None:
    console.print("[bold]2. Library & Index[/bold]")

    blocks_dir = _blocks_dir()
    if blocks_dir.exists():
        n_blocks = len(list(blocks_dir.rglob("*.yaml")))
        console.print(
            f"  [green]✓[/green] Library: {n_blocks} blocks found in {blocks_dir}"
        )
    else:
        console.print(f"  [red]✗[/red] Library not found at {blocks_dir}")

    index_path = _index_path()
    if index_path.exists():
        try:
            with open(index_path, encoding="utf-8") as f:
                header = json.loads(f.readline()).get("header", {})
                model = header.get("model_id", "unknown")
                console.print(
                    f"  [green]✓[/green] Index: Found at {index_path} (Model: {model})"
                )
        except Exception:
            console.print(
                f"  [red]✗[/red] Index at {index_path} is unreadable or malformed"
            )
    else:
        console.print(f"  [red]✗[/red] Index not found at {index_path}")
    console.print()


def _verify_client_registrations(data_dir: Path) -> None:
    console.print("[bold]3. Client Registrations[/bold]")

    table = Table(box=None, padding=(0, 2, 0, 0), show_header=False)

    # Claude Code
    claude_json = Path.home() / ".claude.json"
    _check_json_mcp(claude_json, "Claude Code", table)

    # Gemini CLI
    gemini_json = Path.home() / ".gemini" / "settings.json"
    _check_json_mcp(gemini_json, "Gemini CLI", table)

    # Cursor
    import platform

    if platform.system() == "Darwin":
        cursor_path = (
            Path.home()
            / "Library/Application Support/Cursor/User/globalStorage/saoudrizwan.claude-dev/settings/mcp_servers.json"
        )
        _check_json_mcp(cursor_path, "Cursor", table)

    # Claude Desktop
    if platform.system() == "Darwin":
        desktop_path = (
            Path.home()
            / "Library/Application Support/Claude/claude_desktop_config.json"
        )
        _check_json_mcp(desktop_path, "Claude Desktop", table)

    # Instruction MD files
    _check_md_instructions(
        Path.home() / ".claude" / "CLAUDE.md", "Claude Code (rules)", table
    )
    _check_md_instructions(
        Path.home() / ".gemini" / "GEMINI.md", "Gemini CLI (rules)", table
    )

    console.print(table)
    console.print()


def _check_json_mcp(path: Path, label: str, table: Table) -> None:
    if not path.exists():
        table.add_row(f"  [dim]{label:<20}[/dim]", "[dim]not installed[/dim]")
        return

    try:
        content = path.read_text(encoding="utf-8")
        if "turnzero" in content:
            table.add_row(f"  [green]✓[/green] {label:<20}", "registered")
        else:
            table.add_row(
                f"  [yellow]⚠[/yellow] {label:<20}",
                "[yellow]missing turnzero entry[/yellow]",
            )
    except Exception:
        table.add_row(f"  [red]✗[/red] {label:<20}", "[red]error reading config[/red]")


def _check_md_instructions(path: Path, label: str, table: Table) -> None:
    from turnzero.cli.setup import _TURNZERO_MD_MARKER

    if not path.exists():
        table.add_row(f"  [dim]{label:<20}[/dim]", "[dim]not found[/dim]")
        return

    try:
        content = path.read_text(encoding="utf-8")
        if _TURNZERO_MD_MARKER in content:
            table.add_row(f"  [green]✓[/green] {label:<20}", "rules active")
        else:
            table.add_row(
                f"  [yellow]⚠[/yellow] {label:<20}",
                "[yellow]rules missing or stale[/yellow]",
            )
    except Exception:
        table.add_row(f"  [red]✗[/red] {label:<20}", "[red]error reading file[/red]")


def _verify_retrieval_probe() -> None:
    console.print("[bold]4. Retrieval Probe[/bold]")
    probe_prompt = (
        "Building a FastAPI REST API with Pydantic models and async SQLAlchemy"
    )

    try:
        results = _list_suggested_blocks(probe_prompt)
        if results:
            names = [
                r["block_id"]
                for r in results
                if r.get("block_id") != "personal-priors-limit-warning"
            ]
            console.print(
                f"  [green]✓[/green] Probe successful: found {len(names)} relevant blocks"
            )
            console.print(f"    [dim]Top hits: {', '.join(names[:3])}[/dim]")
        else:
            console.print(
                "  [red]✗[/red] Probe failed: no blocks retrieved for a known implementation prompt"
            )
    except Exception as e:
        console.print(f"  [red]✗[/red] Probe failed with error: {e}")
