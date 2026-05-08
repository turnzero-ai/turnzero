"""turnzero contribute — submit a local candidate as a community issue draft."""

from __future__ import annotations

import shutil
import subprocess

import typer

from turnzero.cli.base import console, err_console
from turnzero.config import get_data_dir


def contribute(
    block_id: str = typer.Argument(..., help="Candidate slug to contribute."),
) -> None:
    """Open a pre-filled GitHub issue draft for a local candidate block."""
    data_dir = get_data_dir()
    cand_path = data_dir / "candidates" / f"{block_id}.yaml"
    if not cand_path.exists():
        err_console.print(f"[red]Candidate '{block_id}' not found.[/red]")
        err_console.print(
            "[dim]Run `turnzero list --candidates` to see pending candidates.[/dim]"
        )
        raise typer.Exit(1)

    content = cand_path.read_text(encoding="utf-8")
    issue_body = (
        "## Expert Prior Candidate\n\n"
        "Submitted from local TurnZero session via `turnzero contribute`.\n\n"
        f"```yaml\n{content}```\n"
    )

    if shutil.which("gh"):
        console.print(f"[dim]🌐 Opening contribution draft for '{block_id}'...[/dim]")
        try:
            subprocess.run(
                [
                    "gh", "issue", "create",
                    "--repo", "turnzero-ai/turnzero",
                    "--title", f"Expert Prior candidate: {block_id}",
                    "--body", issue_body,
                    "--label", "candidate",
                    "--web",
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            err_console.print(f"[red]gh issue create failed: {exc}[/red]")
            raise typer.Exit(1)
    else:
        console.print(f"\n[bold]Contribute '{block_id}' to the community:[/bold]\n")
        console.print(
            "Open: [cyan]https://github.com/turnzero-ai/turnzero/issues/new[/cyan]\n"
            f"Title: [dim]Expert Prior candidate: {block_id}[/dim]\n"
        )
        console.print("Paste this body:\n")
        console.print(issue_body)
        console.print(
            "\n[dim]Install gh CLI for one-command contribution: "
            "https://cli.github.com[/dim]\n"
        )
