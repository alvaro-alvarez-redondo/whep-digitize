"""DataFrame cleaning helpers.

No frame-coercion or defensive-copy helpers are needed: polars is the single engine type
and its frames are immutable. The one meaningful cleaning operation — dropping null-value
rows — is :func:`drop_na_value_rows`.
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
