"""Top-level orchestrator.

Runs the four stages (setup -> ingest -> postpro -> export) in fixed order and reports the
elapsed time. Nothing runs on import: every stage is an explicit call that returns a typed
result, and :func:`run_pipeline` chains those calls.
"""

from __future__ import annotations

import time
from pathlib import Path

from whep_digitize.contracts import OutputResult
from whep_digitize.export.runner import run_export_pipeline
from whep_digitize.ingest.runner import run_ingest_pipeline
from whep_digitize.postpro.runner import run_postpro_pipeline
from whep_digitize.setup.helpers.console import alert_success
from whep_digitize.setup.helpers.time_format import format_elapsed_time
from whep_digitize.setup.options import RuntimeOptions
from whep_digitize.setup.runner import run_setup_pipeline


def format_completion_summary(elapsed: str) -> str:
    """Build the coloured pipeline-completion summary (for ``alert_success``).

    Args:
        elapsed: The formatted elapsed-time string, as
            :func:`~whep_digitize.setup.helpers.time_format.format_elapsed_time` renders it --
            the same ``H:MM:SS`` clock the stage bars show.

    Returns:
        Rich-markup text without the ``OK`` prefix (``alert_success`` adds it).
    """
    return f"Pipeline completed in [bold bright_yellow]{elapsed}[/]"


def run_pipeline(
    *,
    show_view: bool = False,
    dataset_name: str | None = None,
    root: Path | str | None = None,
    options: RuntimeOptions | None = None,
) -> OutputResult:
    """Run the setup -> ingest -> postpro -> export pipeline in order.

    Args:
        show_view: Reserved for an interactive view of the result; currently a no-op.
        dataset_name: Dataset name; defaults to the constant default.
        root: Project root; defaults to the resolved project root.
        options: Runtime options; defaults are used when ``None``.

    Returns:
        The :class:`~whep_digitize.contracts.OutputResult` of the run.
    """
    _ = show_view  # accepted to keep the signature stable; no interactive view is implemented
    start = time.perf_counter()
    effective_options = options if options is not None else RuntimeOptions()

    # Each stage's progress bar is labelled with the stage name, so no separate announcement
    # is printed here.
    config = run_setup_pipeline(dataset_name=dataset_name, root=root, options=effective_options)
    ingest_result = run_ingest_pipeline(config, effective_options)
    postpro_result = run_postpro_pipeline(
        ingest_result.data,
        config,
        dataset_name=config.dataset_name,
        options=effective_options,
    )
    export_result = run_export_pipeline(
        config, postpro_result, raw=ingest_result.data, options=effective_options
    )

    alert_success(format_completion_summary(format_elapsed_time(time.perf_counter() - start)))
    return export_result
