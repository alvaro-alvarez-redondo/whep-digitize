"""Top-level orchestrator.

Runs the four stages (setup -> ingest -> postpro -> export) in fixed order and reports
elapsed time plus the harmonized row/column counts. Nothing runs on import: every stage is an
explicit call that returns a typed result, and :func:`run_pipeline` chains those calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from whep_digitize.contracts import ExportResult
from whep_digitize.export.runner import run_export_pipeline
from whep_digitize.ingest.runner import run_import_pipeline
from whep_digitize.postpro.runner import run_postpro_pipeline
from whep_digitize.setup.helpers.console import alert_success
from whep_digitize.setup.helpers.time_format import format_elapsed_time
from whep_digitize.setup.options import RuntimeOptions
from whep_digitize.setup.runner import run_setup_pipeline

# The progress bars draw their left "|" edge at column 30 (a 1-char spinner + space +
# "running stage: " + a 12-wide label + space). The alert's "OK " prefix is 3 columns, so
# padding "Pipeline completed in <elapsed>" to 27 lands the summary "|" directly under those
# edges. Kept in sync by hand with helpers.progress (_STAGE_WORD length + _LABEL_WIDTH).
_SEPARATOR_COLUMN = 27


def _multiplication_sign() -> str:
    """Return the multiplication sign where the stdout encoding allows, else ASCII ``x``."""
    sign = chr(0xD7)  # multiplication sign, kept out of the source as a literal
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        sign.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return "x"
    return sign


def format_completion_summary(elapsed: str, harmonized_rows: int, harmonized_cols: int) -> str:
    """Build the coloured, aligned pipeline-completion summary (for ``alert_success``).

    The ``|`` separator is padded to line up under the progress bars' left edge, the counts are
    bold bright-yellow, and the multiplication sign is used where the console encoding allows it.
    Shared by :func:`run_pipeline` and the interactive ``whep-digitize.py`` runner so both match.

    Args:
        elapsed: The formatted elapsed-time string.
        harmonized_rows: Row count of the harmonized frame.
        harmonized_cols: Column count of the harmonized frame.

    Returns:
        Rich-markup text without the ``OK`` prefix (``alert_success`` adds it).
    """
    prefix = f"Pipeline completed in {elapsed}"
    pad = " " * max(1, _SEPARATOR_COLUMN - len(prefix))
    return (
        f"Pipeline completed in [bold bright_yellow]{elapsed}[/]{pad}[dim]|[/] "
        f"[bold bright_yellow]{harmonized_rows}[/] harmonized rows {_multiplication_sign()} "
        f"[bold bright_yellow]{harmonized_cols}[/] cols"
    )


def run_pipeline(
    *,
    show_view: bool = False,
    dataset_name: str | None = None,
    root: Path | str | None = None,
    options: RuntimeOptions | None = None,
) -> ExportResult:
    """Run the setup -> ingest -> postpro -> export pipeline in order.

    Args:
        show_view: Reserved for an interactive view of the result; currently a no-op.
        dataset_name: Dataset name; defaults to the constant default.
        root: Project root; defaults to the resolved project root.
        options: Runtime options; defaults are used when ``None``.

    Returns:
        The :class:`~whep_digitize.contracts.ExportResult` of the run.
    """
    _ = show_view  # accepted to keep the signature stable; no interactive view is implemented
    start = time.perf_counter()
    effective_options = options if options is not None else RuntimeOptions()

    # Each stage's progress bar carries its own "running stage: <label>" line, so no separate
    # announcement is printed here.
    config = run_setup_pipeline(dataset_name=dataset_name, root=root, options=effective_options)
    import_result = run_import_pipeline(config, effective_options)
    postpro_result = run_postpro_pipeline(
        import_result.data,
        config,
        dataset_name=config.dataset_name,
        options=effective_options,
    )
    export_result = run_export_pipeline(
        config, postpro_result, raw=import_result.data, options=effective_options
    )

    elapsed = format_elapsed_time(time.perf_counter() - start)
    harmonized = postpro_result.harmonize
    alert_success(format_completion_summary(elapsed, harmonized.height, harmonized.width))
    return export_result
