"""Wide->long reshape + enrichment.

Unpivots the year columns into ``year`` / ``value`` pairs, appends ``document`` / ``notes`` /
``yearbook`` metadata, drops null-value rows, and orchestrates the per-file transform.

Reshape semantics:

* ``unpivot(index=available_id, on=year_cols)`` keeps exactly ``available_id`` plus the
  unpivoted ``year`` / ``value`` and drops every other column. The year columns are recomputed
  from the cleaned headers on each call rather than carried along on the frame.
* Column order out: ``[available_id..., year, value, document, notes, yearbook]``.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import polars as pl

from whep_digitize.ingest.transform.transform_utils import (
    convert_year_columns,
    identify_year_columns,
    normalize_key_fields,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.frames import drop_na_value_rows
from whep_digitize.setup.options import RuntimeOptions


@dataclass(frozen=True, slots=True)
class TransformResult:
    """One file's transform output: the normalized wide frame plus the long frame."""

    wide_raw: pl.DataFrame
    long_raw: pl.DataFrame


def reshape_to_long(frame: pl.DataFrame, config: Config) -> pl.DataFrame:
    """Unpivot the year columns into ``year`` / ``value`` pairs.

    Args:
        frame: The wide frame (year headers already cleaned).
        config: Pipeline configuration (``column_id`` selects the retained id columns).

    Returns:
        The long frame ``[available_id..., year, value]``; all non-id, non-year columns are
        dropped.

    Raises:
        ValidationError: If no year columns are found.
    """
    year_cols = identify_year_columns(frame, config)
    if not year_cols:
        raise ValidationError("no year columns were identified for reshaping")
    available_id = [col for col in config.column_id if col in frame.columns]
    return frame.unpivot(index=available_id, on=year_cols, variable_name="year", value_name="value")


def add_metadata(
    long_frame: pl.DataFrame, file_name: str, yearbook: str, config: Config
) -> pl.DataFrame:
    """Append ``document`` / ``notes`` / ``yearbook`` columns to a long frame.

    Args:
        long_frame: The long frame from :func:`reshape_to_long`.
        file_name: Source file name -> ``document`` (scalar).
        yearbook: Yearbook identifier -> ``yearbook`` (scalar).
        config: Pipeline configuration (``defaults.notes_value`` -> ``notes``).

    Returns:
        The frame with the three metadata columns appended (in that order).
    """
    return long_frame.with_columns(
        pl.lit(file_name, dtype=pl.String).alias("document"),
        pl.lit(config.defaults.notes_value, dtype=pl.String).alias("notes"),
        pl.lit(yearbook, dtype=pl.String).alias("yearbook"),
    )


def transform_file_df(
    frame: pl.DataFrame,
    file_name: str,
    yearbook: str,
    commodity_name: str,
    config: Config,
    options: RuntimeOptions | None = None,
) -> TransformResult:
    """Transform one file's wide data to the long format.

    Normalizes key fields, cleans year headers, reshapes to long, appends metadata, and drops
    null-value rows (gated by ``RuntimeOptions.drop_na_values``).

    Args:
        frame: The wide frame (a read sheet's output).
        file_name: Source file name.
        yearbook: Yearbook identifier.
        commodity_name: Commodity for this file.
        config: Pipeline configuration.
        options: Runtime options; defaults are used when ``None``.

    Returns:
        A :class:`TransformResult` with the normalized wide frame and the long frame.

    Raises:
        ValidationError: If ``file_name`` / ``yearbook`` / ``commodity_name`` is blank.
    """
    require(len(file_name) >= 1, "file_name must be a non-empty string")
    require(len(yearbook) >= 1, "yearbook must be a non-empty string")
    require(len(commodity_name) >= 1, "commodity_name must be a non-empty string")
    resolved_options = options or RuntimeOptions()

    wide_raw = convert_year_columns(normalize_key_fields(frame, commodity_name, config), config)
    long_raw = drop_na_value_rows(
        add_metadata(reshape_to_long(wide_raw, config), file_name, yearbook, config),
        enabled=resolved_options.drop_na_values,
    )
    return TransformResult(wide_raw=wide_raw, long_raw=long_raw)


def build_empty_transform_result() -> TransformResult:
    """Return a transform result with two empty frames."""
    return TransformResult(wide_raw=pl.DataFrame(), long_raw=pl.DataFrame())


def resolve_commodity_name(
    commodity: str | None, config: Config, *, file_name: str | None = None
) -> str:
    """Resolve the commodity for a file, falling back to the unknown-commodity default.

    Args:
        commodity: The raw commodity value from the file metadata (may be ``None`` / blank).
        config: Pipeline configuration (``defaults.unknown_commodity``; the warning is gated
            by ``show_missing_commodity_metadata_warning``).
        file_name: Optional source file name for the warning message.

    Returns:
        The trimmed commodity, or ``config.defaults.unknown_commodity`` when missing / blank.
    """
    name = "" if commodity is None else str(commodity).strip()
    if name == "":
        if config.show_missing_commodity_metadata_warning:
            warnings.warn(
                f"missing commodity metadata detected; using fallback value "
                f"'{config.defaults.unknown_commodity}' (file: {file_name})",
                stacklevel=2,
            )
        return config.defaults.unknown_commodity
    return name
