"""Workbook batching + worker resolution.

Splits discovered workbooks into fixed-size batches, resolves the effective parallel worker
count (``"auto"`` -> ``min(auto_max, cpu_count - 1)``; an explicit count wins, ``1`` forces
sequential), and reads one batch of workbooks (deduplicating repeated paths).

This module holds the sequential batch reader plus the resolvers; the parallel orchestration
over batches lives in :mod:`whep_digitize.ingest.transform.processing`. Because polars frames
are immutable, a repeated path yields the same frame reference twice instead of a copy.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial

import polars as pl

from whep_digitize.ingest.reading.read_utils import (
    ReadResult,
    normalize_pipeline_read_result,
    safe_execute_read,
)
from whep_digitize.ingest.reading.sheet_read import read_file_sheets
from whep_digitize.setup.config import Config
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.options import RuntimeOptions


@dataclass(frozen=True, slots=True)
class BatchReadResult:
    """A batch read: one frame per input path (input order, duplicates repeated) + errors."""

    read_data_list: tuple[pl.DataFrame, ...]
    errors: tuple[str, ...] = ()


def split_workbook_batches(file_paths: Sequence[str] | None, batch_size: int) -> list[list[str]]:
    """Divide file paths into consecutive batches of at most ``batch_size``.

    Args:
        file_paths: Paths to batch (empty or ``None`` -> no batches).
        batch_size: Positive batch size.

    Returns:
        A list of path batches, each of length ``<= batch_size``.

    Raises:
        ValidationError: If ``batch_size`` is below 1.
    """
    require(batch_size >= 1, "batch_size must be >= 1")
    paths = list(file_paths) if file_paths else []
    return [paths[start : start + batch_size] for start in range(0, len(paths), batch_size)]


def resolve_import_workbook_batch_size(config: Config) -> int:
    """Resolve the workbook batch size from ``config``."""
    batch_size = int(config.performance.ingest_workbook_batch_size)
    require(batch_size >= 1, "ingest_workbook_batch_size must be >= 1")
    return batch_size


def resolve_import_effective_workers(config: Config, options: RuntimeOptions | None = None) -> int:
    """Resolve the effective import worker count (>= 1).

    The ``ingest_parallel_workers`` option (:class:`~whep_digitize.setup.options.RuntimeOptions`,
    the ``WHEP_*`` env layer) wins over the constant default. The ``"auto"`` sentinel resolves to
    ``min(auto_max, cpu_count - 1)`` (workbook reading is I/O + serialization bound, so returns
    taper past ~8 workers); an explicit integer is honored, with anything below 1 forced to
    sequential (``1``).

    Args:
        config: Pipeline configuration (supplies ``auto_max``).
        options: Runtime options; defaults are used when ``None``.

    Returns:
        A worker count ``>= 1``.
    """
    resolved = (options or RuntimeOptions()).ingest_parallel_workers
    if resolved == "auto":  # == config.performance.ingest_parallel_workers_auto_token
        auto_max = config.performance.ingest_parallel_workers_auto_max
        cores = os.cpu_count() or 1
        return max(1, min(auto_max, cores - 1))
    return resolved if resolved >= 1 else 1


def read_workbook_batch(
    file_paths: Sequence[str] | None,
    config: Config,
    sheet_names_by_file: Mapping[str, Sequence[str]] | None = None,
) -> BatchReadResult:
    """Read one batch of workbooks, deduplicating repeated paths.

    Each unique path is read once (via ``read_file_sheets`` wrapped in
    :func:`safe_execute_read`); the results are then mapped back onto the original
    ``file_paths`` order, so a duplicated path yields the same frame twice and repeats its errors.

    Args:
        file_paths: Paths in this batch (empty or ``None`` -> empty result).
        config: Pipeline configuration.
        sheet_names_by_file: Optional per-file restriction of which sheets to read.

    Returns:
        A :class:`BatchReadResult` with one frame per input path and the collected errors.
    """
    paths = list(file_paths) if file_paths else []
    if not paths:
        return BatchReadResult(read_data_list=(), errors=())

    results: dict[str, ReadResult] = {}
    for path in dict.fromkeys(paths):
        mapped = sheet_names_by_file.get(path) if sheet_names_by_file is not None else None
        safe = safe_execute_read(
            partial(read_file_sheets, path, config, mapped),
            "failed to read workbook in batch",
            path,
        )
        results[path] = normalize_pipeline_read_result(safe)

    # Duplicates share the same immutable frame; no defensive copy is needed.
    read_data_list = tuple(results[path].data for path in paths)
    errors = tuple(error for path in paths for error in results[path].errors)
    return BatchReadResult(read_data_list=read_data_list, errors=errors)
