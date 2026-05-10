"""TurnZero CLI — central orchestrator."""

from __future__ import annotations

import typer

from turnzero.cli.base import _version_callback
from turnzero.cli.contribute import contribute
from turnzero.cli.discovery import inject, list_blocks, preview, query, show, stats
from turnzero.cli.domain import domain_app
from turnzero.cli.index import index_app, threshold_test, validate
from turnzero.cli.review import harvest, review
from turnzero.cli.setup import feedback, setup, source_app
from turnzero.cli.telemetry import telemetry
from turnzero.cli.verify import verify

app = typer.Typer(
    name="turnzero",
    help="TurnZero — AI Expert Prior injection for developer sessions.",
    no_args_is_help=True,
)


@app.callback()
def _app_options(
    version: bool | None = typer.Option(  # noqa: UP007
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


# Add sub-apps
app.add_typer(index_app, name="index")
app.add_typer(source_app, name="source")
app.add_typer(domain_app, name="domain")

# Register top-level commands
app.command()(preview)
app.command(name="list")(list_blocks)
app.command()(setup)
app.command()(query)
app.command()(show)
app.command()(inject)
app.command()(contribute)
app.command()(feedback)
app.command()(stats)
app.command()(harvest)
app.command()(review)
app.command()(validate)
app.command()(verify)
app.command(name="doctor")(verify)
app.command()(telemetry)
app.command("threshold-test")(threshold_test)


def cli_entry() -> None:
    """Entry point for the turnzero CLI."""
    import asyncio
    import contextlib
    import os

    from turnzero.cli.base import err_console
    from turnzero.errors import TurnZeroError
    from turnzero.telemetry import flush_pending_threads, flush_telemetry

    try:
        app()
    except TurnZeroError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(exc.exit_code)
    except SystemExit:
        raise
    except Exception as exc:
        if os.environ.get("TURNZERO_DEBUG"):
            raise
        err_console.print(f"[red]Unexpected error: {exc}[/red]")
        err_console.print("[dim]Set TURNZERO_DEBUG=1 for full traceback.[/dim]")
        raise typer.Exit(1)
    finally:
        with contextlib.suppress(Exception):
            flush_pending_threads()  # CLI threads (stats, list, domain, etc.)
        with contextlib.suppress(Exception):
            asyncio.run(flush_telemetry())  # MCP async tasks


if __name__ == "__main__":
    cli_entry()
