"""Numeric coercion and double -> string rendering.

The coercion helpers turn character values into doubles, mapping empty strings and
non-numeric text to null without warnings, and trimming surrounding whitespace.

Also hosts :func:`format_double_fixed`, the double -> string rendering shared by the TSV and
unique-list exporters, and the :func:`format_float_columns` / :func:`format_float_series`
frame-level wrappers around it, so every writer renders doubles identically.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import polars as pl

# Doubles are rendered at 15 significant figures wherever they become text.
_SIGNIFICANT_DIGITS = 15


def coerce_numeric_series(values: pl.Series) -> pl.Series:
    """Coerce a column to ``Float64``; empty/non-numeric entries become null.

    Whitespace is stripped before casting (polars ``cast`` does not trim). Already-numeric
    columns are cast directly.

    Args:
        values: The :class:`polars.Series` to coerce.

    Returns:
        A ``Float64`` :class:`polars.Series`.
    """
    if values.dtype.is_numeric():
        return values.cast(pl.Float64)
    return values.cast(pl.String).str.strip_chars().cast(pl.Float64, strict=False)


def format_double_fixed(value: float) -> str | None:
    """Render one double at 15 significant figures in fixed, never-scientific notation.

    15 significant figures, fixed (never scientific) notation, with trailing zeros and a bare
    trailing ``.`` removed (``1.0`` -> ``"1"``, ``1000.0`` -> ``"1000"``, ``1e16`` ->
    ``"10000000000000000"``). This is the byte-exact rule the processed-data TSV writer and the
    numeric branch of the unique-list exporter both depend on; pinned by the numeric-rendering
    tests in ``tests/export`` and the byte-level export tests in ``tests/parity``. ``NaN`` maps
    to ``None`` (rendered as an empty field); the pipeline produces nulls rather than ``NaN``,
    so this is defensive.

    Args:
        value: The double to render.

    Returns:
        The string rendering, or ``None`` for ``NaN``.
    """
    if math.isnan(value):
        return None
    if math.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    if value == 0.0:  # collapses -0.0 to "0"
        return "0"
    with localcontext() as ctx:
        ctx.prec = _SIGNIFICANT_DIGITS
        ctx.rounding = ROUND_HALF_EVEN
        rounded = +Decimal(value)  # round the exact binary value to 15 significant figures
    text = format(rounded, "f")  # fixed notation; never scientific
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_float_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Return ``frame`` with every float column rendered as contract-conformant strings.

    Non-float columns (string, integer) are left untouched — polars already writes them exactly
    as the output contract requires.

    Args:
        frame: The frame to render.

    Returns:
        The frame with float columns replaced by their string rendering.
    """
    float_columns = [name for name, dtype in frame.schema.items() if dtype.is_float()]
    if not float_columns:
        return frame
    return frame.with_columns(
        [format_float_series(frame[name]).alias(name) for name in float_columns]
    )


def format_float_series(series: pl.Series) -> pl.Series:
    """Render a float :class:`polars.Series` as strings via the cardinality fast path.

    Distinct values are formatted once and mapped back (the idiom used by
    ``helpers.strings.normalize_string``); nulls stay null, which
    :meth:`polars.DataFrame.write_csv` renders as an empty field — the contract's missing-value
    form. ``NaN`` also renders as null, matching :func:`format_double_fixed`.

    Args:
        series: The float series to render.

    Returns:
        A ``String`` series of rendered values.
    """
    uniques = series.drop_nulls().unique().to_list()
    if not uniques:
        return series.cast(pl.String)
    mapping = {value: format_double_fixed(value) for value in uniques}
    return series.replace_strict(mapping, default=None, return_dtype=pl.String)
