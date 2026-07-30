r"""Unique-list cache, workbook write, and orchestration (ports ``04-cache-and-write.R``).

Precomputes per-(layer, column) unique values, then writes one ``unique_<column>.xlsx`` workbook
per configured column. Each workbook has one sheet per distinct layer value-set (identical layers
merged, e.g. ``raw_clean_normalize_harmonize``), no header row, one value per row — matching R
``writexl::write_xlsx(sheet_payloads, col_names = FALSE)``.

Parallelism note: R writes workbooks in parallel only when a non-default ``future`` plan is set;
the pipeline's default plan is sequential, so this port defaults to sequential (deterministic).
When ``RuntimeOptions.export_parallel_workers`` requests it, the per-column workbooks are written
across a :class:`~concurrent.futures.ProcessPoolExecutor` — deterministically: the workbooks are
independent files and ``executor.map`` preserves submission order, so the returned mapping and
every file's bytes are identical to the sequential path regardless of the worker count (with a
graceful fall back to sequential if the pool cannot start).
"""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import xlsxwriter

from whep_digitize.export.lists.merge import (
    resolve_list_sheet_payloads,
    resolve_lists_export_columns,
)
from whep_digitize.export.lists.unique_values import (
    LISTS_SHEET_ORDER,
    build_column_lists_export_path,
    build_layer_tables_by_sheet,
    collect_union_columns,
    compute_unique_column_values,
)
from whep_digitize.export.processed_data.layers import collect_layer_tables_for_export
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.strings import normalize_filename
from whep_digitize.setup.options import RuntimeOptions

# A single workbook holds at most one sheet per layer, so a merged name never exceeds Excel's
# 31-char sheet-name limit (``raw_clean_normalize_harmonize`` is 29).
_UniqueCache = dict[str, dict[str, list[str]]]

# "spawn" for worker parity with the ingest pool (a fresh interpreter per worker; the default on
# Windows/macOS). Workbook writes are independent, so this only parallelizes the file IO.
_MP_SPAWN_CONTEXT = multiprocessing.get_context("spawn")

# xlsxwriter stamps the wall-clock time into ``docProps/core.xml`` (created/modified) and the zip
# member dates, which would make the workbook bytes differ on every run. Pin them to a fixed epoch
# so identical inputs produce byte-identical workbooks (the pipeline's determinism guarantee).
_WORKBOOK_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def build_column_unique_cache(
    layer_by_sheet: Mapping[str, pl.DataFrame], columns: Sequence[str]
) -> _UniqueCache:
    """Precompute unique values for every ``(layer, column)`` pair.

    Ports R ``build_column_unique_cache``. Only the given columns are computed (the caller passes
    the resolved export columns, so the high-cardinality ``value`` column is never summarized).

    Args:
        layer_by_sheet: Layer frames keyed by sheet label.
        columns: The columns to summarize.

    Returns:
        A nested mapping ``cache[sheet_label][column] -> unique values``.
    """
    return {
        sheet: {column: compute_unique_column_values(frame, column) for column in columns}
        for sheet, frame in layer_by_sheet.items()
    }


def write_column_lists_workbook(
    column_name: str,
    unique_cache: _UniqueCache,
    config: Config,
    *,
    overwrite: bool = True,
) -> Path:
    """Write one column's ``unique_<column>.xlsx`` with merged deterministic layer sheets.

    Ports R ``write_column_lists_workbook``. All-equal layers collapse to a single
    ``raw_clean_normalize_harmonize`` sheet; partially equal layers merge into concatenated
    names. Sheets have no header and one value per row.

    Args:
        column_name: The column to write.
        unique_cache: The cache from :func:`build_column_unique_cache`.
        config: The resolved pipeline configuration.
        overwrite: When ``False`` and the target exists, refuse to overwrite.

    Returns:
        The written workbook path.

    Raises:
        ValidationError: If ``overwrite`` is ``False`` and the workbook already exists.
    """
    workbook_path = build_column_lists_export_path(config, column_name)
    if not overwrite and workbook_path.exists():
        raise ValidationError(f"file already exists and overwrite is disabled: {workbook_path}")

    layer_values = {
        layer: unique_cache.get(layer, {}).get(column_name, []) for layer in LISTS_SHEET_ORDER
    }
    sheet_payloads = resolve_list_sheet_payloads(layer_values)
    _write_lists_workbook(workbook_path, sheet_payloads)
    return workbook_path


def export_lists(
    config: Config,
    data_objects: Mapping[str, pl.DataFrame],
    *,
    overwrite: bool = True,
    options: RuntimeOptions | None = None,
) -> dict[str, Path]:
    """Export one ``unique_<column>.xlsx`` workbook per configured, present column.

    Ports R ``export_lists``. Detects the layer tables, groups them by sheet, resolves the
    configured export columns present across layers, guards against two columns normalizing to
    the same filename, and writes each workbook. Writes run sequentially by default; when
    ``options.export_parallel_workers`` requests more than one worker they run across a
    ``ProcessPoolExecutor`` in a deterministic, order-preserving way (identical output either way).

    Args:
        config: The resolved pipeline configuration.
        data_objects: Mapping of layer object name to frame.
        overwrite: Passed through to :func:`write_column_lists_workbook`.
        options: Runtime options; defaults are used when ``None`` (resolves the worker count).

    Returns:
        Mapping of column name -> its written workbook path (in configured-column order).

    Raises:
        ValidationError: If no columns are detected, none of the configured columns are present,
            or two configured columns map to the same workbook filename.
    """
    resolved_options = options or RuntimeOptions()
    layer_tables = collect_layer_tables_for_export(data_objects)
    layer_by_sheet = build_layer_tables_by_sheet(layer_tables)
    union_columns = collect_union_columns(layer_by_sheet)
    if not union_columns:
        raise ValidationError("lists export failed: no columns found across detected layers")

    export_columns = resolve_lists_export_columns(config, union_columns)
    unique_cache = build_column_unique_cache(layer_by_sheet, export_columns)

    stems = [normalize_filename(column) for column in export_columns]
    duplicates = sorted({stem for stem in stems if stems.count(stem) > 1})
    if duplicates:
        raise ValidationError(
            "lists export failed: configured columns map to the same workbook filename "
            f"(colliding stem(s): {tuple(duplicates)}; configured columns: {tuple(export_columns)})"
        )

    workers = _resolve_export_workers(resolved_options, len(export_columns))
    if workers > 1 and len(export_columns) > 1:
        return _export_lists_parallel(config, export_columns, unique_cache, workers, overwrite)
    return {
        column: write_column_lists_workbook(column, unique_cache, config, overwrite=overwrite)
        for column in export_columns
    }


def _resolve_export_workers(options: RuntimeOptions, job_count: int) -> int:
    """Resolve the effective workbook-write worker count (clamped to ``[1, job_count]``)."""
    setting = options.export_parallel_workers
    workers = max(1, (os.cpu_count() or 2) - 1) if setting == "auto" else max(1, int(setting))
    return min(workers, max(job_count, 1))


def _write_workbook_job(job: tuple[Path, Mapping[str, Sequence[str]]]) -> Path:
    """Write one workbook from a ``(path, sheet_payloads)`` job (the process-pool entry point)."""
    path, sheet_payloads = job
    _write_lists_workbook(path, sheet_payloads)
    return path


def _export_lists_parallel(
    config: Config,
    export_columns: Sequence[str],
    unique_cache: _UniqueCache,
    workers: int,
    overwrite: bool,
) -> dict[str, Path]:
    """Write each column's workbook across a process pool, preserving configured-column order.

    Path + sheet-payload resolution and the overwrite guard happen in the main process (so the
    workers receive only picklable ``(Path, payloads)`` jobs); ``executor.map`` yields results in
    submission order. Falls back to sequential if the pool cannot start.
    """
    jobs: list[tuple[Path, Mapping[str, Sequence[str]]]] = []
    for column in export_columns:
        path = build_column_lists_export_path(config, column)
        if not overwrite and path.exists():
            raise ValidationError(f"file already exists and overwrite is disabled: {path}")
        layer_values = {
            layer: unique_cache.get(layer, {}).get(column, []) for layer in LISTS_SHEET_ORDER
        }
        jobs.append((path, resolve_list_sheet_payloads(layer_values)))

    try:
        with ProcessPoolExecutor(max_workers=workers, mp_context=_MP_SPAWN_CONTEXT) as executor:
            written = list(executor.map(_write_workbook_job, jobs))
    except (BrokenProcessPool, OSError):
        written = [_write_workbook_job(job) for job in jobs]
    return dict(zip(export_columns, written, strict=True))


def _write_lists_workbook(path: Path, sheet_payloads: Mapping[str, Sequence[str]]) -> None:
    """Write a no-header, one-value-per-row multi-sheet workbook (R ``write_xlsx`` equivalent).

    The ``created`` property is pinned to :data:`_WORKBOOK_EPOCH` so repeated runs over the same
    data produce byte-identical files (xlsxwriter would otherwise embed the current time).
    """
    with xlsxwriter.Workbook(str(path)) as workbook:
        workbook.set_properties({"created": _WORKBOOK_EPOCH})
        for sheet_name, values in sheet_payloads.items():
            worksheet = workbook.add_worksheet(sheet_name)
            for row_index, value in enumerate(values):
                worksheet.write_string(row_index, 0, value)
