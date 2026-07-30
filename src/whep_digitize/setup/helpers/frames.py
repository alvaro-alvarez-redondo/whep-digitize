"""DataFrame cleaning helpers — the Python port of ``02-data-cleaning.R``.

The R data.table coercion helpers (``ensure_data_table``/``copy_as_data_table``) are
no-ops in polars (frames are already the single engine type and are immutable), so only
the meaningful behavior — dropping null-value rows — is ported here.
"""

from __future__ import annotations

import polars as pl


def drop_na_value_rows(
    frame: pl.DataFrame,
    value_column: str = "value",
    *,
    enabled: bool = True,
) -> pl.DataFrame:
    """Drop rows whose value column is null (R ``drop_na_value_rows``).

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
