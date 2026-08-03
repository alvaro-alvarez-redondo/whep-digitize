"""Sheet-level reading.

Reads each worksheet all-as-text (``pl.read_excel(engine="calamine", infer_schema_length=0)``),
normalizes and canonically renames the headers, drops rows empty across every base column, and
tags each surviving row with the sheet name as the ``variable`` column. Sheets are row-bound
with a diagonal concat, so a sheet contributing extra columns still binds (missing values null).

Note 1 (trailing blank rows): calamine drops trailing/blank source rows instead of surfacing
them as all-null rows. That cannot affect the output, because the base-column non-empty filter
below removes exactly those rows anyway — which is what makes the filtered frame stable no
matter how the reader treats sheet padding (covered by the reading tests on the fixture corpus).

Note 2 (float precision): calamine's own text coercion **rounds** a stored double to about 12
significant digits rather than rendering the shortest string that round-trips it. A cell holding
``0.09999999999999964`` therefore reached the pipeline as ``"0.1"``, and a later ``*1000`` unit
standardization turned ``99.9999999999996`` into ``100``. Each sheet is consequently read
**twice** — once all-as-text, once with dtype inference — and
:func:`restore_numeric_text_precision` rewrites only those text cells that do not round-trip to
the exact stored number. Every other cell is passed through verbatim, so the repair cannot move
a value the text read already got right. Residual limitation: a column holding *both* text and
numbers infers as ``String``, so its numeric cells keep calamine's rounded text — recovering
those would need a reader that exposes per-cell types.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import fastexcel
import polars as pl

from whep_digitize.ingest.reading.header_normalization import (
    normalize_header_names,
    resolve_canonical_header_renames,
    validate_header_normalization,
)
from whep_digitize.ingest.reading.read_utils import (
    ReadResult,
    create_empty_read_result,
    safe_execute_read,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.helpers.assertions import require

# fastexcel logs one line per column it cannot type ("could not determine dtype ... falling back
# to string"). That inference is advisory here — only its numeric columns are consulted — so the
# log is silenced for the duration of the typed read rather than printed once per column, per
# sheet, per workbook.
_FASTEXCEL_DTYPE_LOGGER = "fastexcel.types.dtype"


@contextmanager
def _quiet_dtype_inference() -> Iterator[None]:
    """Silence fastexcel's per-column dtype-fallback log, restoring the previous level after."""
    logger = logging.getLogger(_FASTEXCEL_DTYPE_LOGGER)
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(previous)


def _shortest_round_trip_text(value: float | int) -> str:
    """Render a number as the shortest string that parses back to it.

    Integral doubles lose the ``.0`` (``30.0`` -> ``"30"``), which is what calamine emits for a
    whole-number cell, so a repaired cell stays textually consistent with an unrepaired one.

    Args:
        value: The exact number read from the cell.

    Returns:
        The shortest round-tripping decimal text.
    """
    if isinstance(value, int):
        return str(value)
    text = repr(value)
    return text.removesuffix(".0")


def restore_numeric_text_precision(text_df: pl.DataFrame, typed_df: pl.DataFrame) -> pl.DataFrame:
    """Repair text cells that calamine rounded when stringifying a numeric cell.

    For every numeric column of ``typed_df``, a text cell is rewritten only when it fails to
    parse back to the exact stored number — so a cell calamine rendered faithfully is passed
    through byte-for-byte. The rewrite uses the shortest round-tripping rendering.

    Args:
        text_df: The all-as-text read (the frame the pipeline uses).
        typed_df: The same sheet read with dtype inference; only its numeric columns are read.

    Returns:
        ``text_df``, or a copy with the lossy cells rewritten. Returns ``text_df`` unchanged when
        the two reads disagree on height (nothing can be aligned safely).
    """
    if text_df.height == 0 or text_df.height != typed_df.height:
        return text_df

    repaired: list[pl.Series] = []
    for name, dtype in typed_df.schema.items():
        if not dtype.is_numeric() or name not in text_df.columns:
            continue
        text_col = text_df.get_column(name)
        if text_col.dtype != pl.String:
            continue
        exact = typed_df.get_column(name)
        round_tripped = text_col.cast(pl.Float64, strict=False)
        lossy = exact.is_not_null() & (
            round_tripped.is_null() | (round_tripped != exact.cast(pl.Float64))
        )
        if not bool(lossy.any()):
            continue
        repaired.append(
            pl.Series(
                name,
                [
                    _shortest_round_trip_text(value) if flag else text
                    for text, value, flag in zip(
                        text_col.to_list(), exact.to_list(), lossy.to_list(), strict=True
                    )
                ],
                dtype=pl.String,
            )
        )
    if not repaired:
        return text_df
    return text_df.with_columns(repaired)


def _read_sheet_text(file_path: Path | str, sheet_name: str) -> pl.DataFrame:
    """Read one sheet all-as-text with calamine's float rounding repaired (see the module note)."""
    text_df = pl.read_excel(
        file_path, sheet_name=sheet_name, engine="calamine", infer_schema_length=0
    )
    with _quiet_dtype_inference():
        typed_df = pl.read_excel(
            file_path, sheet_name=sheet_name, engine="calamine", infer_schema_length=None
        )
    return restore_numeric_text_precision(text_df, typed_df)


def compute_non_empty_base_rows(frame: pl.DataFrame, base_cols: Sequence[str]) -> pl.Series:
    """Boolean mask of rows with a non-null, non-blank value in at least one base column.

    A row is kept when at least one base column is non-null and still non-blank after trimming.
    With no base columns the mask is all-``False``, so every row is dropped.

    Args:
        frame: The frame to evaluate (base columns must be present and String-typed).
        base_cols: The base column names to test.

    Returns:
        A boolean :class:`polars.Series` of length ``frame.height``.
    """
    if len(base_cols) == 0:
        return pl.Series("keep", [False] * frame.height, dtype=pl.Boolean)
    keep = pl.any_horizontal(
        pl.col(col).is_not_null() & (pl.col(col).str.strip_chars() != "") for col in base_cols
    )
    return frame.select(keep.alias("keep")).get_column("keep")


def read_excel_sheet(file_path: Path | str, sheet_name: str, config: Config) -> ReadResult:
    """Read one worksheet as text, normalize headers, filter empty rows, tag ``variable``.

    Args:
        file_path: Path to the workbook.
        sheet_name: Worksheet to read.
        config: Pipeline configuration (``column_required`` / ``column_id`` drive canonical
            renames and the base-row filter).

    Returns:
        A :class:`ReadResult`; on a read or header-collision error the data is empty and the
        error is carried. Missing base columns are added as all-null and reported as a warning.
    """
    require(len(str(file_path)) >= 1, "file_path must be a non-empty path")
    require(len(sheet_name) >= 1, "sheet_name must be a non-empty string")
    base_cols = list(config.column_required)
    require(len(base_cols) >= 1, "config.column_required must be non-empty")

    safe = safe_execute_read(
        lambda: _read_sheet_text(file_path, sheet_name),
        f"failed to read sheet '{sheet_name}' in file",
        str(file_path),
    )
    if safe.result is None:
        return create_empty_read_result(safe.errors)
    read_df = safe.result

    read_names = read_df.columns
    normalized_names = normalize_header_names(read_names)
    normalization_errors = validate_header_normalization(
        read_names, normalized_names, str(file_path), sheet_name
    )
    if normalization_errors:
        return create_empty_read_result(normalization_errors)

    canonical_names = list(config.column_required)
    if config.column_id:
        canonical_names = list(dict.fromkeys([*canonical_names, *config.column_id]))
    canonical_names = [name for name in canonical_names if name]

    renames = resolve_canonical_header_renames(read_names, normalized_names, canonical_names)
    if renames.old:
        read_df = read_df.rename(dict(zip(renames.old, renames.new, strict=True)))

    missing_base = [col for col in base_cols if col not in read_df.columns]
    errors: tuple[str, ...] = ()
    if missing_base:
        basename = PurePosixPath(str(file_path)).name
        errors = (
            f"sheet '{sheet_name}' is missing required base columns in file "
            f"'{basename}': {', '.join(missing_base)}",
        )
        read_df = read_df.with_columns(
            pl.lit(None, dtype=pl.String).alias(col) for col in missing_base
        )

    keep_mask = compute_non_empty_base_rows(read_df, base_cols)
    filtered = read_df.filter(keep_mask)
    # `variable` overwrites an existing column of that name, otherwise it is appended.
    filtered = filtered.with_columns(pl.lit(sheet_name, dtype=pl.String).alias("variable"))
    return ReadResult(data=filtered, errors=errors)


def read_file_sheets(
    file_path: Path | str, config: Config, sheet_names: Sequence[str] | None = None
) -> ReadResult:
    """Read every worksheet of a workbook and row-bind the results.

    Args:
        file_path: Path to the workbook.
        config: Pipeline configuration.
        sheet_names: Optional explicit sheet names; when ``None`` they are discovered.

    Returns:
        A :class:`ReadResult` whose data is the diagonal concat of every sheet's rows (union of
        columns, missing values null), with a non-ASCII-sheet-name warning and each sheet's
        errors collected.
    """
    require(len(str(file_path)) >= 1, "file_path must be a non-empty path")
    require(len(config.column_required) >= 1, "config.column_required must be non-empty")

    if sheet_names is None:
        safe = safe_execute_read(
            lambda: list(fastexcel.read_excel(str(file_path)).sheet_names),
            "failed to list sheets in file",
            str(file_path),
        )
        if safe.result is None:
            return create_empty_read_result(safe.errors)
        sheets = safe.result
    else:
        sheets = list(sheet_names)

    if len(sheets) == 0:
        return create_empty_read_result()

    errors: list[str] = []
    non_ascii = [sheet for sheet in sheets if not sheet.isascii()]
    if non_ascii:
        basename = PurePosixPath(str(file_path)).name
        errors.append(f"found non-ascii sheet names in file '{basename}': {', '.join(non_ascii)}")

    sheet_results = [read_excel_sheet(file_path, sheet, config) for sheet in sheets]
    frames = [result.data for result in sheet_results if result.data.width > 0]
    combined = pl.concat(frames, how="diagonal") if frames else pl.DataFrame()
    for result in sheet_results:
        errors.extend(result.errors)
    return ReadResult(data=combined, errors=tuple(errors))
