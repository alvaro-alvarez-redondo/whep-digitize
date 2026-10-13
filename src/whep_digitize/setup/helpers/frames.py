"""DataFrame cleaning helpers.

No frame-coercion or defensive-copy helpers are needed: polars is the single engine type and
its frames are immutable. Three frame-level transforms live here: canonicalizing
semicolon-delimited string cells (:func:`canonicalize_semicolon_string_columns`), dropping
null-value rows (:func:`drop_na_value_rows`), and dropping all-null columns
(:func:`drop_all_null_columns`).
"""

from __future__ import annotations

import polars as pl

from whep_digitize.setup.helpers.strings import canonicalize_token_column


def canonicalize_semicolon_string_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Canonicalize every string column's semicolon-delimited cells.

    Each cell is handled independently: trim token whitespace, drop empty tokens, remove
    duplicates, sort the unique tokens, and rejoin with the pipeline delimiter. Tokens are never
    mixed across rows, cells, or columns. Non-string columns are returned unchanged.

    Args:
        frame: The frame to canonicalize.

    Returns:
        A new frame with every ``String`` column canonicalized, or the original frame when there
        are no string columns.
    """
    string_columns = [
        name for name, dtype in zip(frame.columns, frame.dtypes, strict=True) if dtype == pl.String
    ]
    if not string_columns:
        return frame
    return frame.with_columns(
        canonicalize_token_column(frame.get_column(column)).alias(column)
        for column in string_columns
    )


def drop_na_value_rows(
    frame: pl.DataFrame,
    value_column: str = "value",
    *,
    enabled: bool = True,
) -> pl.DataFrame:
    """Drop rows whose value column is null.

    Args:
        frame: The frame to filter.
        value_column: Name of the value column.
        enabled: Gate flag (from ``RuntimeOptions.drop_na_values``). When ``False`` the
            frame is returned unchanged.

    Returns:
        The filtered frame (unchanged if disabled or the column is absent).
    """
    if not enabled or value_column not in frame.columns:
        return frame
    return frame.filter(pl.col(value_column).is_not_null())


def drop_all_null_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Drop every column whose values are entirely null.

    "Empty" means missing (``null``) only — a column of nothing but empty strings is real
    data, not absence of it, and is left alone. Every remaining column keeps its dtype and
    position; only whole columns are removed, never rows.

    Two degenerate cases return ``frame`` unchanged rather than collapse it:

    * A zero-row frame — with no rows there is nothing to judge a column empty *against*
      (every column would vacuously qualify), and dropping them all would erase the frame's
      schema rather than describe its data.
    * A frame whose columns are *all* null — polars carries a frame's row count on its
      columns, so removing the last one collapses the whole frame to ``(0, 0)`` and the row
      count itself is lost, not just the (already-absent) data. Leaving it untouched keeps
      that count visible instead of silently discarding it.

    Args:
        frame: The frame to prune.

    Returns:
        ``frame`` with its all-null columns removed, or ``frame`` itself when there are none,
        it has no rows, or removing them all would leave zero columns.
    """
    if frame.height == 0:
        return frame
    empty_columns = [
        name for name in frame.columns if frame.get_column(name).null_count() == frame.height
    ]
    if not empty_columns or len(empty_columns) == frame.width:
        return frame
    return frame.drop(empty_columns)
