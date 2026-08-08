"""Numeric coercion and double -> string rendering.

The coercion helpers turn character values into doubles, mapping empty strings and
non-numeric text to null without warnings, and trimming surrounding whitespace.

Also hosts :func:`format_double_fixed`, the double -> string rendering shared by the TSV and
unique-list exporters.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import polars as pl

# Doubles are rendered at 15 significant figures wherever they become text.
_SIGNIFICANT_DIGITS = 15


def coerce_numeric(value: str | float | int | bool | None) -> float | None:
    """Coerce a single value to ``float``; empty/non-numeric/``None`` become ``None``.

    Whitespace is trimmed before parsing (``" 2.5 "`` -> ``2.5``). Booleans are treated
    as non-numeric text and return ``None`` (they are never valid pipeline values).

    Args:
        value: The value to coerce.

    Returns:
        The parsed float, or ``None``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


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
