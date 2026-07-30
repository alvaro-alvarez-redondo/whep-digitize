"""Sheet-level reading — the Python port of ``11-sheet-read.R``.

Reads each worksheet all-as-text (``pl.read_excel(engine="calamine", infer_schema_length=0)``
— the readxl ``col_types="text"`` analogue), normalizes and canonically renames the headers,
drops rows empty across every base column, and tags each surviving row with the sheet name as
the ``variable`` column. Sheets are row-bound with a diagonal concat (R ``rbindlist(use.names,
fill)``).

Parity note: readxl and calamine disagree on trailing/blank source rows (readxl keeps them,
calamine drops them), but the base-column non-empty filter removes exactly those rows, so the
filtered output is byte-identical (verified on the corpus — see the parity test).

R source: ``r/1-import_pipeline/11-reading/11-sheet-read.R``.
"""

from __future__ import annotations

from collections.abc import Sequence
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


def compute_non_empty_base_rows(frame: pl.DataFrame, base_cols: Sequence[str]) -> pl.Series:
    """Boolean mask of rows with a non-null, non-blank value in at least one base column.

    Mirrors R ``compute_non_empty_base_rows``: ``Reduce(|, !is.na(v) & trimws(v) != "")`` over
    the base columns. With no base columns every row is dropped (R ``logical(nrow)``).

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
        lambda: pl.read_excel(
            file_path, sheet_name=sheet_name, engine="calamine", infer_schema_length=0
        ),
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
    # R `filtered_df[, variable := sheet_name]`: overwrite in place if present, else append.
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
        A :class:`ReadResult` whose data is the diagonal concat of every sheet's rows (R
        ``rbindlist(use.names = TRUE, fill = TRUE)``), with a non-ASCII-sheet-name warning and
        each sheet's errors collected.
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
