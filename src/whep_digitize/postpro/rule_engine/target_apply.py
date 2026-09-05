"""Apply target-column updates for the ``concatenate`` strategy.

``apply_target_updates_with_strategy`` resolves candidate row updates for one target column
using the ``concatenate`` strategy: join a row's candidates with the delimiter, then merge
into the existing value (order-preserving, existing-first token dedupe).

Other strategies (``token_substitute``, ``last_rule_wins``) are handled by
``conditional_group`` via symmetric token substitution and should not reach this module.

Every scatter is functional: a join-back on a synthesized row index plus
``when/then/otherwise``. ``dataset_df`` is never mutated — the updated frame is returned in
:class:`TargetApplyResult`.

Deliberate behaviors (do not "fix" these):

* The explicit wildcard token is honoured; ``#EXACT#`` suppresses it so a literal
  ``#ANY#`` can be matched.
* Wildcard candidates whose value is already present in the current cell are dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.rule_engine.matching_strategy import (
    get_target_update_strategy_config,
)
from whep_digitize.postpro.rule_engine.matching_values import (
    concatenate_existing_and_incoming_values,
    count_elementwise_value_changes,
    match_rule_target_condition_values,
)
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require

_CONSTANTS = get_pipeline_constants()
_WILDCARD_TOKEN = _CONSTANTS.postpro.rule_match_wildcard_token
# The whitespace class trimmed from values: space, tab, CR, LF.
_TRIM_CHARS = " \t\r\n"
# Internal working-column names (prefixed to avoid colliding with dataset/update columns).
_ROW_ID_INTERNAL = "__whep_row_id_internal__"
_UPDATE_VALUE = "__whep_update_value__"


@dataclass(frozen=True, slots=True)
class TargetApplyResult:
    """Result of applying target updates for one column.

    Attributes:
        applied: Whether any update was applied.
        dataset: The updated dataset (returned; the input frame is never mutated).
        changed_value_count: Number of dataset cells whose value actually changed.
    """

    applied: bool
    dataset: pl.DataFrame
    changed_value_count: int


def _scatter_column(
    dataset: pl.DataFrame, target_column: str, indices: Sequence[int], values: pl.Series
) -> pl.DataFrame:
    """Return ``dataset`` with ``target_column`` overwritten at ``indices`` by ``values``.

    Functional scatter: a left join on a
    synthesized row index plus ``when/then/otherwise``. ``indices`` are 0-based and unique;
    ``values`` aligns positionally with them. A ``None`` in ``values`` overwrites to null.

    Args:
        dataset: The frame to update (not mutated).
        target_column: The column to overwrite.
        indices: 0-based row indices to update (unique).
        values: Replacement values, aligned with ``indices``.

    Returns:
        A new frame with the scattered column (original row order preserved).
    """
    index_name = "__whep_scatter_index__"
    new_value_name = "__whep_scatter_value__"
    matched_name = "__whep_scatter_matched__"
    update_map = pl.DataFrame(
        {
            index_name: pl.Series(index_name, list(indices), dtype=pl.UInt32),
            new_value_name: values.cast(pl.String),
            matched_name: pl.Series(matched_name, [True] * len(indices), dtype=pl.Boolean),
        }
    )
    return (
        dataset.with_row_index(index_name)
        .join(update_map, on=index_name, how="left")
        .with_columns(
            pl.when(pl.col(matched_name).fill_null(False))
            .then(pl.col(new_value_name))
            .otherwise(pl.col(target_column).cast(pl.String))
            .alias(target_column)
        )
        .sort(index_name)
        .drop(index_name, new_value_name, matched_name)
    )


def _zero_based(row_ids: Sequence[int]) -> list[int]:
    """Convert 1-based dataset row ids to 0-based gather/scatter indices."""
    return [row_id - 1 for row_id in row_ids]


def apply_target_updates_with_strategy(
    dataset: pl.DataFrame,
    target_updates: pl.DataFrame,
    target_column: str,
    *,
    row_id_column: str = "row_id",
    value_column: str = "value_target_result",
    condition_column: str = "value_target_raw",
    order_columns: Sequence[str] = (),
    apply_condition_match: bool = True,
    dataset_name: str,
    execution_stage: str,
    rule_file_identifier: str,
    source_column: str,
) -> TargetApplyResult:
    """Apply conditional and unconditional updates to one target column (``concatenate`` only).

    This function handles the ``concatenate`` strategy. Other strategies
    (``token_substitute``, ``last_rule_wins``) are dispatched by ``conditional_group``
    and should not reach this entry point.

    Args:
        dataset: The dataset to update (returned updated; never mutated in place).
        target_updates: Candidate row updates (row id, value, optional condition).
        target_column: The column to update.
        row_id_column: The 1-based row-id column in ``target_updates``.
        value_column: The update-value column in ``target_updates``.
        condition_column: The optional target-condition column in ``target_updates``.
        order_columns: Columns to deterministically (stable-)order updates before reduction.
        apply_condition_match: Whether to filter conditioned updates by condition match.
        dataset_name: Dataset identifier.
        execution_stage: Execution stage label.
        rule_file_identifier: Rule file identifier.
        source_column: Source column name.

    Returns:
        A :class:`TargetApplyResult` with the updated dataset and change count.

    Raises:
        ValidationError: If a required string argument is empty, ``target_column`` or a required
            update column is missing, a row id is out of bounds, the ``concatenate`` target is
            not string-typed, or the resolved strategy is not ``concatenate``.
    """
    for name, value in (
        ("target_column", target_column),
        ("row_id_column", row_id_column),
        ("value_column", value_column),
        ("condition_column", condition_column),
        ("dataset_name", dataset_name),
        ("execution_stage", execution_stage),
        ("rule_file_identifier", rule_file_identifier),
        ("source_column", source_column),
    ):
        require(len(value) >= 1, f"{name} must be a non-empty string")

    if target_updates.height == 0:
        return TargetApplyResult(False, dataset, 0)

    if target_column not in dataset.columns:
        raise ValidationError(f"target column '{target_column}' is missing in dataset")

    missing_columns = [
        column
        for column in (row_id_column, value_column, condition_column)
        if column not in target_updates.columns
    ]
    if missing_columns:
        raise ValidationError(
            f"target updates are missing required columns: {', '.join(missing_columns)}"
        )

    updates = target_updates
    present_order_columns = list(
        dict.fromkeys(column for column in order_columns if column in updates.columns)
    )
    if present_order_columns:
        # Stable ascending sort with nulls first.
        updates = updates.sort(present_order_columns, nulls_last=False, maintain_order=True)

    updates = updates.with_columns(
        pl.col(row_id_column).cast(pl.Int64, strict=False).alias(_ROW_ID_INTERNAL)
    ).filter(pl.col(_ROW_ID_INTERNAL).is_not_null())

    if updates.height == 0:
        return TargetApplyResult(False, dataset, 0)

    row_id_values = updates.get_column(_ROW_ID_INTERNAL)
    if ((row_id_values < 1) | (row_id_values > dataset.height)).any():
        raise ValidationError("target updates contain row indexes outside dataset boundaries")

    strategy_config = get_target_update_strategy_config()

    if apply_condition_match:
        updates = _apply_condition_match(
            updates,
            dataset,
            target_column=target_column,
            value_column=value_column,
            condition_column=condition_column,
        )

    if updates.height == 0:
        return TargetApplyResult(False, dataset, 0)

    strategy = strategy_config.by_column.get(target_column, strategy_config.default)

    if strategy != "concatenate":
        raise ValidationError(
            f"target_apply only handles the 'concatenate' strategy; "
            f"got '{strategy}' for '{target_column}'. "
            "Other strategies are dispatched by conditional_group."
        )

    return _apply_concatenate(
        updates,
        dataset,
        target_column=target_column,
        value_column=value_column,
        delimiter=strategy_config.concatenate_delimiter,
    )


def _apply_condition_match(
    updates: pl.DataFrame,
    dataset: pl.DataFrame,
    *,
    target_column: str,
    value_column: str,
    condition_column: str,
) -> pl.DataFrame:
    """Filter conditioned updates by condition match and drop no-op wildcard candidates.

    Conditioned rows whose condition does not match the current dataset value are dropped;
    the surviving conditioned rows are appended after the unconditional rows. Wildcard
    candidates whose value is already present in the current cell are removed.
    """
    has_condition = pl.col(condition_column).is_not_null()
    conditioned_raw = updates.filter(has_condition)
    if conditioned_raw.height == 0:
        return updates

    current_values = dataset.get_column(target_column).gather(
        _zero_based(conditioned_raw.get_column(_ROW_ID_INTERNAL).to_list())
    )
    condition_matches = match_rule_target_condition_values(
        current_values,
        conditioned_raw.get_column(condition_column),
    )
    conditioned = conditioned_raw.filter(condition_matches)

    if conditioned.height > 0:
        condition_series = conditioned.get_column(condition_column)
        is_wildcard = condition_series.is_not_null() & (
            condition_series.str.strip_chars(_TRIM_CHARS).str.to_lowercase()
            == _WILDCARD_TOKEN.lower()
        )
        if is_wildcard.any():
            wildcard_current = dataset.get_column(target_column).gather(
                _zero_based(conditioned.get_column(_ROW_ID_INTERNAL).to_list())
            )
            already_present = match_rule_target_condition_values(
                wildcard_current,
                conditioned.get_column(value_column),
            )
            conditioned = conditioned.filter(~(is_wildcard & already_present))

    unconditional = updates.filter(~has_condition)
    return pl.concat([unconditional, conditioned], how="vertical")


def _apply_concatenate(
    updates: pl.DataFrame,
    dataset: pl.DataFrame,
    *,
    target_column: str,
    value_column: str,
    delimiter: str,
) -> TargetApplyResult:
    """Apply the ``concatenate`` strategy (per-row paste, then order-preserving token merge)."""
    if dataset.schema[target_column] != pl.String:
        raise ValidationError(
            "concatenate strategy requires a character-like target column; "
            f"column {target_column} has type: {dataset.schema[target_column]}"
        )

    updates = updates.with_columns(
        pl.col(value_column).cast(pl.String).alias(_UPDATE_VALUE)
    ).with_columns(
        pl.when(pl.col(_UPDATE_VALUE).str.strip_chars(_TRIM_CHARS).str.len_chars() == 0)
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(pl.col(_UPDATE_VALUE))
        .alias(_UPDATE_VALUE)
    ).filter(pl.col(_UPDATE_VALUE).is_not_null())

    if updates.height == 0:
        return TargetApplyResult(False, dataset, 0)

    collapsed = updates.group_by(_ROW_ID_INTERNAL, maintain_order=True).agg(
        pl.col(_UPDATE_VALUE).str.join(delimiter).alias(_UPDATE_VALUE)
    )
    indices = _zero_based(collapsed.get_column(_ROW_ID_INTERNAL).to_list())
    existing_values = dataset.get_column(target_column).gather(indices)
    merged_values = concatenate_existing_and_incoming_values(
        existing_values, collapsed.get_column(_UPDATE_VALUE), delimiter
    )
    new_dataset = _scatter_column(dataset, target_column, indices, merged_values)
    after = new_dataset.get_column(target_column).gather(indices)
    changed = count_elementwise_value_changes(existing_values, after)
    return TargetApplyResult(True, new_dataset, changed)
