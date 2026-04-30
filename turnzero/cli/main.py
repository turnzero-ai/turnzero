"""TurnZero CLI — central orchestrator."""

from __future__ import annotations

import typer

from turnzero.cli.base import _version_callback
from turnzero.cli.discovery import inject, preview, query, show, stats
from turnzero.cli.index import index_app, threshold_test, validate
from turnzero.cli.review import harvest, review
from turnzero.cli.setup import autolearn, feedback, setup, source_app
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

# Register top-level commands
app.command()(preview)
app.command()(setup)
app.command()(query)
app.command()(show)
app.command()(inject)
app.command()(feedback)
app.command()(stats)
app.command()(autolearn)
app.command()(harvest)
app.command()(review)
app.command()(validate)
app.command()(verify)
app.command(name="doctor")(verify)
app.command("threshold-test")(threshold_test)

if __name__ == "__main__":
    app()
