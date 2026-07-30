"""Command-line interface (``whep-digitize``).

A thin :mod:`typer` front-end over :func:`whep_digitize.pipeline.run_pipeline` and the
Stage-0 bootstrap.
"""

from __future__ import annotations

import typer

from whep_digitize.pipeline import run_pipeline
from whep_digitize.setup.helpers.console import alert_success, get_console
from whep_digitize.setup.runner import run_setup_pipeline

app = typer.Typer(help="WHEP digitize pipeline.", no_args_is_help=True, add_completion=False)


@app.command()
def run(
    *,
    show_view: bool = False,
    dataset: str | None = None,
) -> None:
    """Run the full pipeline (setup -> ingest -> postpro -> export)."""
    run_pipeline(show_view=show_view, dataset_name=dataset)


@app.command()
def bootstrap(*, dataset: str | None = None) -> None:
    """Run only Stage 0: build the config and create the directory tree."""
    config = run_setup_pipeline(dataset_name=dataset)
    console = get_console()
    alert_success(f"bootstrapped dataset '{config.dataset_name}'")
    console.print(f"  project root : {config.project_root}")
    console.print(f"  import (raw) : {config.paths.data.import_.raw}")
    console.print(f"  audit        : {config.paths.data.audit.audit_dir}")
    console.print(f"  export       : {config.paths.data.export.processed}")


if __name__ == "__main__":
    app()
