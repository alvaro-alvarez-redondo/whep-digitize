"""Command-line interface (``whep-digitize``).

A thin :mod:`typer` front-end over :func:`whep_digitize.pipeline.run_pipeline` and the
Stage-0 bootstrap.
"""

from __future__ import annotations

from typing import Annotated

import typer

from whep_digitize.pipeline import run_pipeline
from whep_digitize.setup.helpers.console import alert_success, get_console
from whep_digitize.setup.runner import run_setup_pipeline

ShowViewOption = Annotated[
    bool,
    typer.Option("--show-view/--no-view", help="Show the optional interactive result view."),
]
DatasetOption = Annotated[
    str | None,
    typer.Option("--dataset", "-d", help="Dataset name to use for generated outputs."),
]

app = typer.Typer(
    help="WHEP digitize pipeline.",
    invoke_without_command=True,
    no_args_is_help=False,
    add_completion=False,
)


@app.callback()
def main(
    ctx: typer.Context,
    *,
    show_view: ShowViewOption = False,
    dataset: DatasetOption = None,
) -> None:
    """Run the full pipeline when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        run_pipeline(show_view=show_view, dataset_name=dataset)


@app.command()
def run(
    *,
    show_view: ShowViewOption = False,
    dataset: DatasetOption = None,
) -> None:
    """Run the full pipeline (setup -> ingest -> postpro -> export)."""
    run_pipeline(show_view=show_view, dataset_name=dataset)


@app.command()
def bootstrap(*, dataset: DatasetOption = None) -> None:
    """Run only Stage 0: build the config and create the directory tree."""
    config = run_setup_pipeline(dataset_name=dataset)
    console = get_console()
    alert_success(f"bootstrapped dataset '{config.dataset_name}'")
    console.print(f"  project root : {config.project_root}")
    console.print(f"  import (raw) : {config.paths.data.input.raw}")
    console.print(f"  audit        : {config.paths.data.audit.audit_dir}")
    console.print(f"  export       : {config.paths.data.output.processed}")


if __name__ == "__main__":
    app()
