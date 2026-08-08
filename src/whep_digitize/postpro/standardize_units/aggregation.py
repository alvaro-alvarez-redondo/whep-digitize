"""Postpro / standardize_units — post-standardization duplicate-group aggregation.

Collapses rows that are identical on every column except the numeric measure by summing that
measure, with deterministic all-missing semantics (a group whose every value is null sums to
null). Column order and schema are preserved and the operation is idempotent (re-running on an
already-unique table is a no-op).

Frames are returned, never mutated in place.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require

_VALUE_COLUMN = "value"


def _duplicate_group_mask(dataset: pl.DataFrame, group_cols: list[str]) -> pl.Series:
    """Boolean mask of rows that belong to a duplicate group."""
    if dataset.height == 0 or len(group_cols) == 0:
        return pl.Series("mask", [False] * dataset.height, dtype=pl.Boolean)
    return dataset.select(pl.struct(group_cols).is_duplicated().alias("mask")).get_column("mask")


def _aggregate_duplicate_groups(
    dataset: pl.DataFrame, group_cols: list[str], value_column: str
) -> pl.DataFrame:
    """Sum ``value_column`` per group (first-appearance order); an all-null group sums to null."""
    return dataset.group_by(group_cols, maintain_order=True).agg(
        pl.when(pl.col(value_column).count() == 0)
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(value_column).sum())
        .alias(value_column)
    )


def aggregate_standardized_rows(
    dataset: pl.DataFrame, value_column: str = _VALUE_COLUMN
) -> pl.DataFrame:
    """Collapse duplicate groups by summing the measure, preserving column order + schema.

    Groups are defined by every column
    except ``value_column``. Unique rows are kept (original order) ahead of the aggregated
    duplicate groups (first-appearance order); an all-null group sums to null. Idempotent.

    Args:
        dataset: The frame to aggregate.
        value_column: The numeric measure column to sum.

    Returns:
        The aggregated frame (unchanged when there are no duplicate groups).

    Raises:
        ValidationError: If ``value_column`` is absent.
    """
    if value_column not in dataset.columns:
        raise ValidationError(f"value column '{value_column}' not found in data")
    if dataset.height <= 1:
        return dataset

    group_cols = [column for column in dataset.columns if column != value_column]
    if not group_cols:
        values = dataset.get_column(value_column)
        aggregated = None if values.null_count() == values.len() else values.sum()
        return pl.DataFrame(
            {value_column: pl.Series(value_column, [aggregated], dtype=values.dtype)}
        )

    mask = _duplicate_group_mask(dataset, group_cols)
    if not bool(mask.any()):
        return dataset

    if bool(mask.all()):
        return _aggregate_duplicate_groups(dataset, group_cols, value_column).select(
            dataset.columns
        )

    unique_rows = dataset.filter(~mask)
    aggregated_rows = _aggregate_duplicate_groups(dataset.filter(mask), group_cols, value_column)
    return pl.concat([unique_rows, aggregated_rows], how="diagonal").select(dataset.columns)


def extract_aggregated_rows(
    dataset: pl.DataFrame, value_column: str = _VALUE_COLUMN
) -> pl.DataFrame:
    """Return only the rows that :func:`aggregate_standardized_rows` will collapse.

    the rows belonging to a duplicate group
    (groups defined by every column except ``value_column``); an empty same-schema frame when
    there are no duplicates.

    Args:
        dataset: The pre-aggregation frame.
        value_column: The numeric measure column.

    Returns:
        The duplicate-group rows (same column order/schema), or an empty same-schema frame.

    Raises:
        ValidationError: If ``value_column`` is absent.
    """
    require(value_column in dataset.columns, f"value column '{value_column}' not found in data")
    if dataset.height == 0:
        return dataset

    group_cols = [column for column in dataset.columns if column != value_column]
    if not group_cols:
        return dataset.clear()

    mask = _duplicate_group_mask(dataset, group_cols)
    if not bool(mask.any()):
        return dataset.clear()
    return dataset.filter(mask)
