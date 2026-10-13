"""Stage 3 runner — export orchestration.

Assembles the layer objects (``whep_data_raw`` from the ingest output plus the postpro
``clean`` / ``normalize`` / ``harmonize`` frames), canonicalizes each and drops any column that
came out entirely null, ensures the export directories exist, writes the processed-data TSVs
and the per-column unique-list workbooks, and returns the validated
:class:`~whep_digitize.contracts.OutputResult`.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.contracts import OutputResult, PostproResult, assert_output_paths_contract
from whep_digitize.export.lists.write import export_lists
from whep_digitize.export.processed_data.export import export_processed_data
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import ensure_directories_exist
from whep_digitize.setup.helpers.frames import (
    canonicalize_semicolon_string_columns,
    drop_all_null_columns,
)
from whep_digitize.setup.helpers.progress import stage_progress
from whep_digitize.setup.options import RuntimeOptions

_MESSAGES = get_pipeline_constants().progress.messages["export"]


def run_export_pipeline(
    config: Config,
    result: PostproResult,
    *,
    raw: pl.DataFrame | None = None,
    overwrite: bool = True,
    options: RuntimeOptions | None = None,
) -> OutputResult:
    """Export processed-data TSVs and per-column unique-list workbooks.

    Builds the canonically-named layer mapping (``whep_data_raw`` when ``raw`` is supplied, plus
    ``whep_data_clean`` / ``_normalize`` / ``_harmonize`` from the post-processing result), creates
    the export directories, then writes both export families and asserts the paths contract.

    Each layer is canonicalized and pruned of all-null columns independently (see
    :func:`~whep_digitize.setup.helpers.frames.drop_all_null_columns`) before either export
    family reads it, so two layers of the same dataset can legitimately end up with different
    column sets — e.g. a rule fills ``notes`` in ``harmonize`` but it stayed empty upstream, so
    only ``raw`` and ``clean`` lose that column. Both ``export_processed_data`` and
    ``export_lists`` already tolerate a column missing from one layer but not another.

    Args:
        config: The resolved pipeline configuration.
        result: The post-processing result (source of the clean/normalize/harmonize layers).
        raw: The raw import layer (exported as ``whep_data_raw``); included in the unique-list
            export when provided. ``None`` omits the raw sheet.
        overwrite: Whether to overwrite existing output files.
        options: Runtime options; defaults are used when ``None`` (gates the progress bar and
            resolves the list-export worker count).

    Returns:
        An :class:`~whep_digitize.contracts.OutputResult` of object/column names to written paths.
    """
    resolved_options = options or RuntimeOptions()
    object_names = get_pipeline_constants().object_names
    data_objects: dict[str, pl.DataFrame] = {}
    if raw is not None:
        data_objects[object_names.raw] = _prepare_export_layer(raw)
    data_objects[object_names.clean] = _prepare_export_layer(result.clean)
    data_objects[object_names.normalize] = _prepare_export_layer(result.normalize)
    data_objects[object_names.harmonize] = _prepare_export_layer(result.harmonize)

    ensure_directories_exist([config.paths.data.output.processed, config.paths.data.output.lists])

    with stage_progress("export", total=2, enabled=resolved_options.progress_enabled) as progress:
        progress.step(_MESSAGES["processed"])
        processed_paths = export_processed_data(config, data_objects, overwrite=overwrite)
        progress.step(_MESSAGES["lists"])
        lists_paths = export_lists(
            config, data_objects, overwrite=overwrite, options=resolved_options
        )

    export_result = OutputResult(processed_paths=processed_paths, lists_paths=lists_paths)
    assert_output_paths_contract(export_result)
    return export_result


def _prepare_export_layer(frame: pl.DataFrame) -> pl.DataFrame:
    """Canonicalize one layer frame, then drop its all-null columns.

    Canonicalization only rewrites cell content (it never changes which cells are null — a
    null stays null through :func:`canonicalize_semicolon_string_columns`), so the drop always
    sees the same null pattern that will actually reach the export writers.

    Args:
        frame: The layer frame to prepare (postpro output, or the raw ingest frame).

    Returns:
        The canonicalized frame with any entirely-null column removed.
    """
    return drop_all_null_columns(canonicalize_semicolon_string_columns(frame))
