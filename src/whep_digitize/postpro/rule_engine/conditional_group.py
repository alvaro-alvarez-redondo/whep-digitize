"""Apply one source->target conditional rule group.

The Python port of ``r/2-postpro_pipeline/23-postpro_rule_engine/23-conditional-group.R``
(``apply_conditional_rule_group`` + ``prepare_conditional_rule_group``). For one
``(column_source, column_target)`` rule group it:

1. builds deterministic match keys for each rule (source key, target-condition key, encoded
   target result);
2. cartesian-joins every dataset row to the rules on the source key, then keeps rows whose
   current target value also satisfies the rule's target condition;
3. rewrites the **source** column for matched rules that carry a source-result value, and
   updates the **target** column via :func:`apply_target_updates_with_strategy`;
4. emits a per-rule audit table and reports the changed columns **independently** — a group
   whose only effect was a source rewrite marks the source column, not the target.

R mutates ``dataset_df`` by reference (``data.table::set`` + the target-apply scatter); this
port is functional and returns the updated frame in :class:`ConditionalGroupResult`. The
cartesian join reproduces data.table's Y-then-X row order (dataset row, then rule order) via an
explicit ``__rule_order__`` sort, which the source/target last-rule-wins reductions depend on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.rule_engine.matching_strategy import (
    decode_target_rule_value,
    empty_last_rule_wins_overwrite_events_df,
    encode_rule_match_key,
    encode_target_rule_value,
    get_target_update_strategy_config,
    resolve_rule_match_normalization_settings,
    resolve_tokenized_target_condition_columns,
)
from whep_digitize.postpro.rule_engine.matching_values import (
    count_elementwise_value_changes,
    match_rule_target_condition_values,
)
from whep_digitize.postpro.rule_engine.target_apply import apply_target_updates_with_strategy
from whep_digitize.postpro.utilities.stage_definitions import (
    get_stage_source_value_column,
    get_stage_target_value_column,
    validate_postpro_stage_name,
)
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require

# R ``trimws()`` default whitespace class is ``[ \t\r\n]``; match it exactly.
_R_TRIMWS_CHARS = " \t\r\n"
_RULE_ORDER = "__whep_rule_order__"
_CURRENT_TARGET = "__whep_current_target__"
_AUDIT_KEY = ("source_key", "target_key", "value_source_result", "value_target_result_encoded")
_AUDIT_ORDER = ("column_source", "column_target", "value_source_raw", "value_target_raw")


@dataclass(frozen=True, slots=True)
class PreparedConditionalGroup:
    """A validated conditional rule group (R ``prepare_conditional_rule_group``)."""

    group_rules: pl.DataFrame
    stage_name: str


@dataclass(frozen=True, slots=True)
class ConditionalGroupResult:
    """Result of applying one conditional rule group (R ``list(data, audit, ...)``).

    Attributes:
        data: The updated dataset (R mutated its argument in place; this port returns it).
        audit: One row per applied rule (empty when nothing changed).
        overwrite_events: Last-rule-wins overwrite diagnostics from the target update.
        changed_value_count: Total source + target cell changes.
        changed_columns: The columns actually changed (source and/or target), independently.
    """

    data: pl.DataFrame
    audit: pl.DataFrame
    overwrite_events: pl.DataFrame
    changed_value_count: int
    changed_columns: tuple[str, ...]


def prepare_conditional_rule_group(
    group_rules: pl.DataFrame, stage_name: str
) -> PreparedConditionalGroup:
    """Validate one conditional rule group for later application.

    Args:
        group_rules: Canonical rules for one source/target column pair (at least one row).
        stage_name: The execution stage (validated).

    Returns:
        The prepared group.

    Raises:
        ValidationError: If ``group_rules`` is empty or the stage is unsupported.
    """
    require(group_rules.height >= 1, "group_rules must have at least one row")
    stage = validate_postpro_stage_name(stage_name)
    return PreparedConditionalGroup(group_rules=group_rules, stage_name=stage)


def _scatter_column(
    dataset: pl.DataFrame, column: str, indices: Sequence[int], values: pl.Series
) -> pl.DataFrame:
    """Return ``dataset`` with ``column`` overwritten at (unique) 0-based ``indices`` by ``values``.

    The functional analogue of ``data.table::set``: a left join on a synthesized row index plus
    ``when/then/otherwise``. A ``None`` in ``values`` overwrites to null.
    """
    index_name = "__whep_scatter_index__"
    value_name = "__whep_scatter_value__"
    matched_name = "__whep_scatter_matched__"
    update_map = pl.DataFrame(
        {
            index_name: pl.Series(index_name, list(indices), dtype=pl.UInt32),
            value_name: values.cast(pl.String),
            matched_name: pl.Series(matched_name, [True] * len(indices), dtype=pl.Boolean),
        }
    )
    return (
        dataset.with_row_index(index_name)
        .join(update_map, on=index_name, how="left")
        .with_columns(
            pl.when(pl.col(matched_name).fill_null(False))
            .then(pl.col(value_name))
            .otherwise(pl.col(column).cast(pl.String))
            .alias(column)
        )
        .sort(index_name)
        .drop(index_name, value_name, matched_name)
    )


def _build_normalize_rules(
    group: pl.DataFrame,
    *,
    source_value_column: str,
    target_value_column: str,
    apply_source_norm: bool,
    apply_target_norm: bool,
) -> pl.DataFrame:
    """Build the deduplicated, keyed rule table (R ``normalize_rules``)."""
    value_source_raw = group.get_column("value_source_raw")
    value_target_raw = group.get_column("value_target_raw")
    normalize_rules = pl.DataFrame(
        {
            "column_source": group.get_column("column_source"),
            "value_source_raw": value_source_raw,
            "source_value_raw": group.get_column(source_value_column),
            "source_value_column_present": group.get_column("source_value_column_present"),
            "column_target": group.get_column("column_target"),
            "value_target_raw": value_target_raw,
            "value_target_result_encoded": encode_target_rule_value(
                group.get_column(target_value_column)
            ),
            "source_key": encode_rule_match_key(
                value_source_raw, apply_normalization=apply_source_norm
            ),
            "target_key": encode_rule_match_key(
                value_target_raw, apply_normalization=apply_target_norm
            ),
        }
    ).unique(maintain_order=True)

    decoded_target = decode_target_rule_value(
        normalize_rules.get_column("value_target_result_encoded")
    ).rename("value_target_result")
    return (
        normalize_rules.with_columns(
            pl.col("source_value_raw").cast(pl.String).alias("value_source_result"),
            decoded_target,
        )
        .with_columns(
            pl.when(
                pl.col("value_source_result").str.strip_chars(_R_TRIMWS_CHARS).str.len_chars() == 0
            )
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col("value_source_result"))
            .alias("value_source_result")
        )
        .with_row_index(_RULE_ORDER)
    )


def apply_conditional_rule_group(
    dataset: pl.DataFrame,
    *,
    group_rules: pl.DataFrame | None = None,
    stage_name: str,
    dataset_name: str,
    rule_file_id: str,
    execution_timestamp_utc: str,
    apply_match_normalization: bool = True,
    prepared_group: PreparedConditionalGroup | None = None,
) -> ConditionalGroupResult:
    """Apply one ``(column_source, column_target)`` conditional rule group to the dataset.

    Args:
        dataset: The dataset to update (returned updated; never mutated in place).
        group_rules: Canonical rules for the group (mutually exclusive with ``prepared_group``).
        stage_name: The execution stage (validated).
        dataset_name: Dataset identifier (for audit / overwrite events).
        rule_file_id: Rule file identifier (for audit / overwrite events).
        execution_timestamp_utc: Execution timestamp (for the audit table).
        apply_match_normalization: Whether to normalize match keys.
        prepared_group: A prepared group (mutually exclusive with ``group_rules``).

    Returns:
        A :class:`ConditionalGroupResult` with the updated dataset, audit, overwrite events,
        total change count, and the independently-reported changed columns.

    Raises:
        ValidationError: If not exactly one of ``group_rules`` / ``prepared_group`` is given, the
            group is empty, or a required string argument is empty.
    """
    if (group_rules is None) == (prepared_group is None):
        raise ValidationError("exactly one of group_rules or prepared_group must be provided")
    if prepared_group is not None:
        group_rules = prepared_group.group_rules
    assert group_rules is not None  # narrowed by the XOR check above
    require(group_rules.height >= 1, "group_rules must have at least one row")
    stage = validate_postpro_stage_name(stage_name)
    require(len(dataset_name) >= 1, "dataset_name must be a non-empty string")
    require(len(rule_file_id) >= 1, "rule_file_id must be a non-empty string")
    require(len(execution_timestamp_utc) >= 1, "execution_timestamp_utc must be a non-empty string")

    target_value_column = get_stage_target_value_column(stage)
    source_value_column = get_stage_source_value_column(stage)
    excluded_columns = resolve_rule_match_normalization_settings().excluded_columns

    group = group_rules
    source_value_column_present = source_value_column in group.columns
    if source_value_column not in group.columns:
        group = group.with_columns(pl.lit(None, dtype=pl.String).alias(source_value_column))
    if "source_value_column_present" not in group.columns:
        group = group.with_columns(
            pl.lit(source_value_column_present).alias("source_value_column_present")
        )

    source_column = group.get_column("column_source")[0]
    target_column = group.get_column("column_target")[0]
    apply_source_norm = apply_match_normalization and source_column not in excluded_columns
    apply_target_norm = apply_match_normalization and target_column not in excluded_columns

    normalize_rules = _build_normalize_rules(
        group,
        source_value_column=source_value_column,
        target_value_column=target_value_column,
        apply_source_norm=apply_source_norm,
        apply_target_norm=apply_target_norm,
    )
    tokenized_columns = resolve_tokenized_target_condition_columns(
        get_target_update_strategy_config()
    )

    source_pre = dataset.get_column(source_column)
    target_pre = dataset.get_column(target_column)
    join_input = pl.DataFrame(
        {
            "row_id": pl.Series("row_id", range(1, dataset.height + 1), dtype=pl.Int64),
            "source_key": encode_rule_match_key(source_pre, apply_normalization=apply_source_norm),
        }
    )

    # data.table X[Y] keeps Y (dataset) rows, joining X (rules) columns; cartesian on multi-match.
    # The (row_id, rule-order) sort reproduces its deterministic order, which the source/target
    # last-rule-wins reductions rely on.
    joined = join_input.join(normalize_rules, on="source_key", how="left").sort(
        ["row_id", _RULE_ORDER], nulls_last=True, maintain_order=True
    )
    current_target = target_pre.gather(
        [row_id - 1 for row_id in joined.get_column("row_id").to_list()]
    )
    joined = joined.with_columns(current_target.alias(_CURRENT_TARGET))

    source_matched = joined.get_column("column_source").is_not_null()
    # Computing the condition match over every joined row (then AND-ing with the source match) is
    # equivalent to R's matched-subset computation: unmatched rows are masked out regardless.
    target_condition = match_rule_target_condition_values(
        joined.get_column(_CURRENT_TARGET),
        joined.get_column("value_target_raw"),
        tokenized_target=target_column in tokenized_columns,
        apply_match_normalization=apply_target_norm,
    )
    matched_row_mask = source_matched & target_condition
    source_update_mask = matched_row_mask & joined.get_column(
        "source_value_column_present"
    ).fill_null(False)

    new_dataset = dataset
    overwrite_events = empty_last_rule_wins_overwrite_events_df()
    source_changed = 0
    target_changed = 0

    if bool(matched_row_mask.any()):
        new_dataset, source_changed = _apply_source_rewrite(
            new_dataset, joined, source_update_mask, source_column, source_pre
        )
        target_result = apply_target_updates_with_strategy(
            new_dataset,
            joined.filter(matched_row_mask).select(
                "row_id", "value_target_raw", "value_target_result"
            ),
            target_column,
            row_id_column="row_id",
            value_column="value_target_result",
            condition_column="value_target_raw",
            order_columns=["row_id"],
            apply_condition_match=False,
            dataset_name=dataset_name,
            execution_stage=stage,
            rule_file_identifier=rule_file_id,
            source_column=source_column,
        )
        new_dataset = target_result.dataset
        overwrite_events = target_result.overwrite_events
        target_changed = target_result.changed_value_count

    audit = _build_audit(
        joined,
        normalize_rules,
        audit_mask=matched_row_mask if (source_changed + target_changed) > 0 else None,
        dataset_name=dataset_name,
        execution_timestamp_utc=execution_timestamp_utc,
        rule_file_id=rule_file_id,
        stage=stage,
    )

    changed_columns: list[str] = []
    if source_changed > 0:
        changed_columns.append(source_column)
    if target_changed > 0 and target_column not in changed_columns:
        changed_columns.append(target_column)

    return ConditionalGroupResult(
        data=new_dataset,
        audit=audit,
        overwrite_events=overwrite_events,
        changed_value_count=source_changed + target_changed,
        changed_columns=tuple(changed_columns),
    )


def _apply_source_rewrite(
    dataset: pl.DataFrame,
    joined: pl.DataFrame,
    source_update_mask: pl.Series,
    source_column: str,
    source_pre: pl.Series,
) -> tuple[pl.DataFrame, int]:
    """Rewrite the source column for source-update rows (last rule wins per row).

    The change count is taken over every source-update row (with duplicate row ids), matching R's
    ``count_elementwise_value_changes`` over the un-deduplicated before/after vectors.
    """
    if not bool(source_update_mask.any()):
        return dataset, 0

    source_updates = joined.filter(source_update_mask)
    all_row_ids = source_updates.get_column("row_id").to_list()
    before = source_pre.gather([row_id - 1 for row_id in all_row_ids])

    last_per_row = source_updates.group_by("row_id", maintain_order=True).agg(
        pl.col("value_source_result").last()
    )
    new_dataset = _scatter_column(
        dataset,
        source_column,
        [row_id - 1 for row_id in last_per_row.get_column("row_id").to_list()],
        last_per_row.get_column("value_source_result"),
    )
    after = new_dataset.get_column(source_column).gather([row_id - 1 for row_id in all_row_ids])
    return new_dataset, count_elementwise_value_changes(before, after)


def _build_audit(
    joined: pl.DataFrame,
    normalize_rules: pl.DataFrame,
    *,
    audit_mask: pl.Series | None,
    dataset_name: str,
    execution_timestamp_utc: str,
    rule_file_id: str,
    stage: str,
) -> pl.DataFrame:
    """Build the per-rule audit table (empty when nothing changed)."""
    audited = joined.filter(audit_mask) if audit_mask is not None else joined.clear()
    matched_counts = audited.group_by(list(_AUDIT_KEY), maintain_order=True).agg(
        pl.len().alias("affected_rows")
    )
    return (
        matched_counts.join(normalize_rules, on=list(_AUDIT_KEY), how="left")
        .select(
            pl.lit(dataset_name).alias("dataset_name"),
            "column_source",
            "value_source_raw",
            "value_source_result",
            "column_target",
            "value_target_raw",
            "value_target_result",
            pl.col("affected_rows").fill_null(0).cast(pl.Int64),
            pl.lit(execution_timestamp_utc).alias("execution_timestamp_utc"),
            pl.lit(rule_file_id).alias("rule_file_identifier"),
            pl.lit(stage).alias("execution_stage"),
        )
        .sort(list(_AUDIT_ORDER), nulls_last=True, maintain_order=True)
    )
