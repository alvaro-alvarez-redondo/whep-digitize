"""Fused read+transform per batch.

Executes read and transform as one unit of work per workbook batch: each batch reads its
workbooks (:func:`~whep_digitize.ingest.reading.batching.read_workbook_batch`) and immediately
transforms each file (:func:`transform_single_file`), so the bulky intermediate wide read data
never crosses back to the main process. Batches run sequentially by default, or across a
:class:`~concurrent.futures.ProcessPoolExecutor` when more than one worker and more than one
batch are available — with a graceful fall back to sequential if the pool cannot start.

**Determinism:** the combined output is independent of the worker count. ``executor.map``
yields batch results in submission order, and batch order + within-batch file order preserve
the global file order, so parallel output is byte-identical to sequential output.

Because a :class:`~whep_digitize.setup.config.Config` is not picklable (it nests
``mappingproxy`` constants), workers receive the picklable ``(dataset_name, project_root)``
and rebuild an identical config with :func:`~whep_digitize.setup.config.load_pipeline_config`
(the config is a pure function of those plus the frozen constants).
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath

import polars as pl

from whep_digitize.ingest.reading.batching import (
    read_workbook_batch,
    resolve_import_effective_workers,
    resolve_import_workbook_batch_size,
    split_workbook_batches,
)
from whep_digitize.ingest.transform.reshape import (
    TransformResult,
    build_empty_transform_result,
    resolve_commodity_name,
    transform_file_df,
)
from whep_digitize.setup.config import Config, load_pipeline_config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.options import RuntimeOptions

_MESSAGES = get_pipeline_constants().progress.messages["ingest"]

# Force the "spawn" start method for worker processes. On Linux the default is "fork", which
# deadlocks when the parent has already initialized polars' (Rayon) thread pool: the child
# inherits copies of mutexes locked by threads that do not exist in it, so it never returns and
# ``executor.map`` blocks forever (this is what hangs CI to its 6h timeout). "spawn" starts a
# fresh interpreter per worker — already the default on Windows/macOS — so batch execution
# behaves identically across platforms.
_MP_SPAWN_CONTEXT = multiprocessing.get_context("spawn")

FileRow = Mapping[str, object]
Progressor = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ReadTransformResult:
    """Fused read+transform output: the combined transform plus the collected read errors."""

    transformed: TransformResult
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BatchObject:
    """A batch's workbook paths plus the matching file-metadata rows (picklable)."""

    paths: tuple[str, ...]
    file_rows: tuple[FileRow, ...]


@dataclass(frozen=True, slots=True)
class _BatchResult:
    """One batch's per-file transforms (``None`` for empty files) and read errors."""

    transforms: tuple[TransformResult | None, ...]
    errors: tuple[str, ...]


def transform_single_file(
    file_row: FileRow,
    df_wide: pl.DataFrame,
    config: Config,
    options: RuntimeOptions | None = None,
) -> TransformResult | None:
    """Transform one file's wide data using its metadata row.

    Args:
        file_row: Metadata row with ``file_name`` / ``yearbook`` / ``commodity`` (extra keys
            are ignored).
        df_wide: The file's wide sheet data.
        config: Pipeline configuration.
        options: Runtime options; defaults are used when ``None``.

    Returns:
        The :class:`TransformResult`, or ``None`` when ``df_wide`` has no rows (dropped
        downstream).

    Raises:
        ValidationError: If ``file_name`` or ``yearbook`` is missing / blank.
    """
    if df_wide.height == 0:
        return None

    file_name = file_row["file_name"]
    yearbook = file_row["yearbook"]
    # Explicit isinstance raises (not require()) so mypy narrows file_name / yearbook to str.
    if not (isinstance(file_name, str) and file_name):
        raise ValidationError("file_row['file_name'] must be a non-empty string")
    if not (isinstance(yearbook, str) and yearbook):
        raise ValidationError("file_row['yearbook'] must be a non-empty string")

    commodity = file_row.get("commodity")
    commodity_str = commodity if isinstance(commodity, str) else None
    commodity_name = resolve_commodity_name(commodity_str, config, file_name=file_name)
    return transform_file_df(df_wide, file_name, yearbook, commodity_name, config, options)


def _read_message(path: str) -> str:
    return _MESSAGES["read_file"].format(name=PurePosixPath(path).name)


def _transform_message(file_name: str) -> str:
    return _MESSAGES["transform_file"].format(name=file_name)


def _emit_batch_ticks(progressor: Progressor, batch: _BatchObject) -> None:
    """Emit one read tick and one transform tick per file in a batch (main-process fallback)."""
    for path in batch.paths:
        progressor(_read_message(path))
    for file_row in batch.file_rows:
        name = file_row.get("file_name")
        progressor(_transform_message(name if isinstance(name, str) else ""))


def _fused_one_batch_impl(
    batch: _BatchObject,
    config: Config,
    options: RuntimeOptions,
    progressor: Progressor | None,
) -> _BatchResult:
    """Read a batch's workbooks then transform each file."""
    if progressor is not None:
        for path in batch.paths:
            progressor(_read_message(path))

    batch_read = read_workbook_batch(list(batch.paths), config)
    transforms: list[TransformResult | None] = []
    for index, file_row in enumerate(batch.file_rows):
        if progressor is not None:
            name = file_row.get("file_name")
            progressor(_transform_message(name if isinstance(name, str) else ""))
        transforms.append(
            transform_single_file(file_row, batch_read.read_data_list[index], config, options)
        )
    return _BatchResult(transforms=tuple(transforms), errors=batch_read.errors)


def _fused_one_batch_worker(
    batch: _BatchObject, dataset_name: str, root: Path, options: RuntimeOptions
) -> _BatchResult:
    """Picklable worker entry point: rebuild the config, then run the batch (no progress)."""
    config = load_pipeline_config(dataset_name, root)
    return _fused_one_batch_impl(batch, config, options, progressor=None)


def _run_sequential(
    batch_objects: Sequence[_BatchObject],
    config: Config,
    options: RuntimeOptions,
    progressor: Progressor | None,
) -> list[_BatchResult]:
    return [_fused_one_batch_impl(batch, config, options, progressor) for batch in batch_objects]


def _run_parallel(
    batch_objects: Sequence[_BatchObject],
    config: Config,
    options: RuntimeOptions,
    workers: int,
    progressor: Progressor | None,
) -> list[_BatchResult]:
    """Run batches on a process pool, preserving order; fall back to sequential on failure."""
    worker = partial(
        _fused_one_batch_worker,
        dataset_name=config.dataset_name,
        root=config.project_root,
        options=options,
    )
    try:
        with ProcessPoolExecutor(max_workers=workers, mp_context=_MP_SPAWN_CONTEXT) as executor:
            results: list[_BatchResult] = []
            # map preserves submission order -> deterministic regardless of completion order.
            mapped = executor.map(worker, batch_objects)
            for batch, batch_result in zip(batch_objects, mapped, strict=True):
                if progressor is not None:
                    _emit_batch_ticks(progressor, batch)
                results.append(batch_result)
            return results
    except (BrokenProcessPool, OSError):
        # Workers could not start / the pool broke: degrade to sequential, same results.
        return _run_sequential(batch_objects, config, options, progressor)


def read_transform_pipeline_files(
    file_list: pl.DataFrame,
    config: Config,
    options: RuntimeOptions | None = None,
    progressor: Progressor | None = None,
) -> ReadTransformResult:
    """Read and transform all pipeline files in fused batches.

    Args:
        file_list: File metadata with at least ``file_path`` (plus ``file_name`` /
            ``yearbook`` / ``commodity`` for the transform).
        config: Pipeline configuration (``column_required`` must be non-empty).
        options: Runtime options; defaults are used when ``None``.
        progressor: Optional per-file progress callback (one read + one transform tick each).

    Returns:
        A :class:`ReadTransformResult` with the combined :class:`TransformResult` and the
        collected read errors. Output is independent of the worker count.

    Raises:
        ValidationError: If ``file_list`` lacks a ``file_path`` column or ``config`` has no
            required columns.
    """
    require("file_path" in file_list.columns, "file_list must have a 'file_path' column")
    require(len(config.column_required) >= 1, "config.column_required must be non-empty")
    resolved_options = options or RuntimeOptions()

    if file_list.height == 0:
        return ReadTransformResult(transformed=build_empty_transform_result(), errors=())

    file_paths = file_list.get_column("file_path").to_list()
    batch_size = resolve_import_workbook_batch_size(config)
    batches = split_workbook_batches(file_paths, batch_size)

    # First index of each path; paths are unique in practice, but stay first-wins.
    first_index: dict[str, int] = {}
    for index, path in enumerate(file_paths):
        first_index.setdefault(path, index)
    batch_objects = [
        _BatchObject(
            paths=tuple(batch_paths),
            file_rows=tuple(file_list.row(first_index[path], named=True) for path in batch_paths),
        )
        for batch_paths in batches
    ]

    workers = resolve_import_effective_workers(config, resolved_options)
    if workers > 1 and len(batch_objects) > 1:
        batch_results = _run_parallel(batch_objects, config, resolved_options, workers, progressor)
    else:
        batch_results = _run_sequential(batch_objects, config, resolved_options, progressor)

    transforms = [
        transform
        for batch_result in batch_results
        for transform in batch_result.transforms
        if transform is not None
    ]
    errors = tuple(error for batch_result in batch_results for error in batch_result.errors)

    if not transforms:
        transformed = build_empty_transform_result()
    else:
        transformed = TransformResult(
            wide_raw=pl.concat([t.wide_raw for t in transforms], how="diagonal"),
            long_raw=pl.concat([t.long_raw for t in transforms], how="diagonal"),
        )
    return ReadTransformResult(transformed=transformed, errors=errors)
