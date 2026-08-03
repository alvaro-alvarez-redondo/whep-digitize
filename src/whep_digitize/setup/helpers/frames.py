"""DataFrame cleaning helpers.

No frame-coercion or defensive-copy helpers are needed: polars is the single engine type
and its frames are immutable. The one meaningful cleaning operation — dropping null-value
rows — is :func:`drop_na_value_rows`.
"""

from __future__ import annotations

import polars as pl


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
