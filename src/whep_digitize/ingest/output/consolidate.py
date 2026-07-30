"""Output consolidation — the Python port of ``13-output.R``.

Row-binds the audited long tables into one frame, fills any missing target-schema columns with
null, and reorders columns to the configured canonical order (extras last). ``rbindlist(...,
use.names, fill)`` becomes ``pl.concat(how="diagonal")``.

R source: ``r/1-import_pipeline/13-output/13-output.R``
(``consolidate_audited_df``, ``validate_output_column_order``).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.helpers.assertions import require

# The full canonical output schema every consolidated frame must contain (R target_schema).
_TARGET_SCHEMA = (
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "value",
    "notes",
    "footnotes",
    "yearbook",
    "document",
)


@dataclass(frozen=True, slots=True)
class ConsolidateResult:
    """Consolidation output (R ``list(data, warnings)``)."""

    data: pl.DataFrame
    warnings: tuple[str, ...]


def validate_output_column_order(config: Config) -> list[str]:
    """Return ``config.column_order``, checked to be unique and to cover the target schema.

    Args:
        config: Pipeline configuration (``column_order``).

    Returns:
        The validated column order.

    Raises:
        ValidationError: If ``column_order`` is empty, has duplicates, or omits a
            target-schema column.
    """
    column_order = list(config.column_order)
    require(len(column_order) >= 1, "config.column_order must be non-empty")
    require(len(set(column_order)) == len(column_order), "config.column_order must be unique")
    ordered = set(column_order)
    missing = [col for col in _TARGET_SCHEMA if col not in ordered]
    require(
        not missing, f"config.column_order must contain the full target schema; missing: {missing}"
    )
    return column_order


def consolidate_audited_df(
    frames: Sequence[pl.DataFrame | None], config: Config
) -> ConsolidateResult:
    """Row-bind audited long tables, fill missing schema columns, and enforce column order.

    Args:
        frames: Frames to combine (``None`` entries are skipped, R ``Filter(Negate(is.null))``).
        config: Pipeline configuration (``column_order``).

    Returns:
        A :class:`ConsolidateResult`; when no frames are given, an empty frame and a
        (verbatim) warning.
    """
    column_order = validate_output_column_order(config)
    items = [frame for frame in frames if frame is not None]

    if not items:
        message = "no data tables were provided for consolidation"
        warnings.warn(message, stacklevel=2)
        return ConsolidateResult(data=pl.DataFrame(), warnings=(message,))

    combined = pl.concat(items, how="diagonal")
    missing = [col for col in column_order if col not in combined.columns]
    if missing:
        combined = combined.with_columns(
            [pl.lit(None, dtype=pl.String).alias(col) for col in missing]
        )
    ordered = set(column_order)
    extra = [col for col in combined.columns if col not in ordered]
    combined = combined.select([*column_order, *extra])
    return ConsolidateResult(data=combined, warnings=())
