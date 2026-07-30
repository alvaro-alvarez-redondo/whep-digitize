r"""Wide-frame transform utilities — the Python port of ``12-transform-utils.R``.

Identifies year columns, normalizes the key identifier fields, and cleans year-column
headers (with a fatal duplicate-collision guard) ahead of the wide->long reshape.

R source: ``r/1-import_pipeline/12-transform/12-transform-utils.R``.
"""

from __future__ import annotations

import re
from collections import Counter

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.strings import (
    clean_footnote_column,
    normalize_string,
    normalize_text,
)

_constants = get_pipeline_constants()
_YEAR_COLUMN_RE = re.compile(_constants.patterns.year_column)  # ^\d{4}(-\d{4})?$

# convert_year_columns header cleanups, applied in this order (R gsub/sub chain).
_EXCEL_SUFFIX_RE = re.compile(r"\.0$")  # "2020.0" -> "2020"
_CROP_YEAR_RE = re.compile(r"^(\d{4})-\d{2}$")  # "2020-21" -> "2020"
_CROP_YEAR_RANGE_RE = re.compile(
    r"^(\d{4})-\d{2}/(\d{4})-\d{2}$"
)  # "2020-21/2021-22" -> "2020-2021"

# Textual identifier columns normalized in place (commodity is set separately; unit stays raw).
_KEY_NORM_COLUMNS = ("variable", "hemisphere", "continent", "polity")


def identify_year_columns(frame: pl.DataFrame, config: Config) -> list[str]:
    r"""Return the frame's year columns in column order.

    Mirrors R ``identify_year_columns``: candidates are the columns *not* among the metadata
    columns (``column_order`` minus ``year`` / ``value``), kept when the name matches the year
    pattern ``^\d{4}(-\d{4})?$``.

    Args:
        frame: The wide frame to inspect.
        config: Pipeline configuration (supplies ``column_order``).

    Returns:
        Year column names, in the frame's column order.
    """
    all_cols = frame.columns
    if not all_cols:
        return []
    non_year = set(config.column_order) - {"year", "value"}
    return [col for col in all_cols if col not in non_year and _YEAR_COLUMN_RE.search(col)]


def normalize_key_fields(frame: pl.DataFrame, commodity_name: str, config: Config) -> pl.DataFrame:
    """Ensure base columns exist and normalize the key identifier fields.

    Adds any missing base columns as all-null, sets ``commodity`` to the normalized
    ``commodity_name`` (a scalar, recycled to every row), normalizes ``variable`` /
    ``hemisphere`` / ``continent`` / ``polity`` where present, and cleans ``footnotes``.
    ``unit`` is intentionally left raw (R normalizes only the four key columns).

    Args:
        frame: The wide frame.
        commodity_name: The commodity for this file (normalized before assignment).
        config: Pipeline configuration (supplies ``column_required``).

    Returns:
        A new frame with the normalized key fields.
    """
    result = frame
    missing = [col for col in config.column_required if col not in result.columns]
    if missing:
        result = result.with_columns([pl.lit(None, dtype=pl.String).alias(col) for col in missing])

    result = result.with_columns(
        pl.lit(normalize_text(commodity_name), dtype=pl.String).alias("commodity")
    )

    norm_cols = [col for col in _KEY_NORM_COLUMNS if col in result.columns]
    if norm_cols:
        result = result.with_columns(
            [normalize_string(result.get_column(col)).alias(col) for col in norm_cols]
        )
    if "footnotes" in result.columns:
        result = result.with_columns(
            clean_footnote_column(result.get_column("footnotes")).alias("footnotes")
        )
    return result


def _clean_year_header(name: str) -> str:
    """Strip Excel ``.0`` suffixes and normalize crop-year header formats."""
    name = _EXCEL_SUFFIX_RE.sub("", name)
    name = _CROP_YEAR_RE.sub(r"\1", name)
    return _CROP_YEAR_RANGE_RE.sub(r"\1-\2", name)


def convert_year_columns(frame: pl.DataFrame, config: Config) -> pl.DataFrame:
    """Clean year-column headers, guarding against collisions.

    Removes Excel numeric suffixes and normalizes crop-year header formats, then renames the
    columns. If two source headers clean to the same name (e.g. a calendar ``"2020"`` and a
    crop-year ``"2020-21"`` both becoming ``"2020"``) it aborts, mirroring R's ``cli_abort`` —
    otherwise the reshape would silently drop one column's observations.

    The R string coercion of year columns is a no-op here (calamine reads all-as-text) and the
    ``whep_year_columns`` attribute is *not* carried; :func:`reshape_to_long` recomputes the
    year columns explicitly (parity risk #2).

    Args:
        frame: The wide frame.
        config: Pipeline configuration.

    Returns:
        The frame with cleaned year-column headers.

    Raises:
        ValidationError: If the header cleanup produces duplicate column names.
    """
    _ = config  # only used by the caller's reshape; kept for signature parity with R
    original = frame.columns
    clean = [_clean_year_header(name) for name in original]

    counts = Counter(clean)
    if any(count > 1 for count in counts.values()):
        colliding = [name for name in dict.fromkeys(clean) if counts[name] > 1]
        raise ValidationError(
            f"year-column normalization produced duplicate column names: {colliding} "
            f"(original columns: {original})"
        )

    if clean != original:
        frame = frame.rename(dict(zip(original, clean, strict=True)))
    return frame
