"""Apply one source->target conditional rule group.

``apply_conditional_rule_group`` (with ``prepare_conditional_rule_group``) applies one
``(column_source, column_target)`` rule group. For each group it:

1. builds deterministic match keys for each rule (source key, target-condition key, encoded
   target result);
2. explodes each source cell on ``;`` into one match candidate per token, plus one candidate for
   the whole cell, and cartesian-joins those candidates to the rules on the source key; a rule
   matches tokens by default and the whole cell only when marked ``#EXACT#``. Matched candidates
   are then kept only where the current target value satisfies the rule's target condition;
3. rewrites the **source** column **element-wise** — a matched token is substituted in place and
   its siblings are preserved, then the cell is rebuilt deduplicated and sorted — and updates the
   **target** column via :func:`apply_target_updates_with_strategy`;
4. emits a per-rule audit table and reports the changed columns **independently** — a group
   whose only effect was a source rewrite marks the source column, not the target.

``dataset_df`` is never mutated: the flow is functional and returns the updated frame in
:class:`ConditionalGroupResult`. The cartesian join is ordered by (dataset row, rule order) via an
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
    resolve_rule_match_normalization_settings,
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
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.strings import (
    canonicalize_token_cell,
    resolve_exact_match_directive,
)

# The whitespace class trimmed from values: space, tab, CR, LF.
_TRIM_CHARS = " \t\r\n"
_TOKEN_DELIMITER = get_pipeline_constants().postpro.target_update_strategies.concatenate_delimiter
_RULE_ORDER = "__whep_rule_order__"
_CURRENT_TARGET = "__whep_current_target__"
_TOKEN_INDEX = "__whep_token_index__"
_IS_FULL_CELL = "__whep_is_full_cell__"
_RULE_IS_EXACT = "__whep_rule_is_exact__"
# Token index reserved for the whole-cell candidate that #EXACT# rules match against.
_FULL_CELL_INDEX = -1
_AUDIT_KEY = ("source_key", "target_key", "value_source_result", "value_target_result_encoded")
_AUDIT_ORDER = ("column_source", "column_target", "value_source_raw", "value_target_raw")
# Sentinel for null-safe joins: polars does not match null to null, so null audit keys are
# folded to this token before joining matched counts with normalize rules.
_AUDIT_NA_SENTINEL = get_pipeline_constants().na_match_key


@dataclass(frozen=True, slots=True)
class PreparedConditionalGroup:
    """A validated conditional rule group."""

    group_rules: pl.DataFrame
    stage_name: str


@dataclass(frozen=True, slots=True)
class ConditionalGroupResult:
    """Result of applying one conditional rule group.

    Attributes:
        data: The updated dataset (returned; the input frame is never mutated).
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

    Functional scatter: a left join on a synthesized row index plus
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
    """Build the deduplicated, keyed rule table."""
    value_source_raw = group.get_column("value_source_raw")
    value_target_raw = group.get_column("value_target_raw")
    # The #EXACT# marker is a directive, not data: strip it before keying so the key is the value
    # the author meant, and carry the flag so the join can require the matching mode.
    resolved_source = [resolve_exact_match_directive(value) for value in value_source_raw.to_list()]
    source_match_values = pl.Series(
        "source_match_values", [body for body, _ in resolved_source], dtype=pl.String
    )
    rule_is_exact = pl.Series(
        _RULE_IS_EXACT, [is_exact for _, is_exact in resolved_source], dtype=pl.Boolean
    )
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
            _RULE_IS_EXACT: rule_is_exact,
            "source_key": encode_rule_match_key(
                source_match_values, apply_normalization=apply_source_norm
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
            pl.when(pl.col("value_source_result").str.strip_chars(_TRIM_CHARS).str.len_chars() == 0)
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

    source_pre = dataset.get_column(source_column)
    target_pre = dataset.get_column(target_column)
    join_input, per_row_tokens = _explode_source_candidates(
        source_pre, apply_normalization=apply_source_norm
    )

    # Left join keeps every candidate and fans out on a multi-rule match. The
    # (row_id, token-index, rule-order) sort makes that order deterministic, which the
    # source/target last-rule-wins reductions rely on.
    joined = join_input.join(normalize_rules, on="source_key", how="left").sort(
        ["row_id", _TOKEN_INDEX, _RULE_ORDER], nulls_last=True, maintain_order=True
    )
    current_target = target_pre.gather(
        [row_id - 1 for row_id in joined.get_column("row_id").to_list()]
    )
    joined = joined.with_columns(current_target.alias(_CURRENT_TARGET))

    # A rule matches in exactly one mode: an ``#EXACT#`` rule against the full-cell candidate, a
    # plain rule against each exploded token. Requiring the flags to agree keeps the two modes
    # from ever matching the same candidate.
    source_matched = joined.get_column("column_source").is_not_null() & (
        joined.get_column(_IS_FULL_CELL) == joined.get_column(_RULE_IS_EXACT).fill_null(False)
    )
    # Computing the condition over every joined row and AND-ing with the source match is
    # equivalent to evaluating it on the matched subset: unmatched rows are masked out regardless.
    target_condition = match_rule_target_condition_values(
        joined.get_column(_CURRENT_TARGET),
        joined.get_column("value_target_raw"),
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
            new_dataset, joined, source_update_mask, source_column, source_pre, per_row_tokens
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


def _explode_source_candidates(
    source: pl.Series, *, apply_normalization: bool
) -> tuple[pl.DataFrame, list[list[str]]]:
    """Build one match candidate per source token, plus one for the whole cell.

    Element-wise matching is the default, so every canonical token of the source cell is offered
    as a candidate. One extra candidate carries the full cell, which is what an ``#EXACT#`` rule
    matches against. A row with no tokens (null / blank cell) still gets its full-cell candidate,
    so exact rules can target missing values.

    Args:
        source: The source column.
        apply_normalization: Whether match keys are normalized.

    Returns:
        ``(candidates, per_row_tokens)`` — the candidate frame and, per dataset row, its canonical
        token list (index-aligned with the candidates' ``token_index``).
    """
    row_ids: list[int] = []
    token_indexes: list[int] = []
    is_full_cell: list[bool] = []
    key_inputs: list[str | None] = []
    per_row_tokens: list[list[str]] = []

    for row_id, cell in enumerate(source.cast(pl.String).to_list(), start=1):
        canonical = canonicalize_token_cell(cell)
        tokens = canonical.split(_TOKEN_DELIMITER) if canonical is not None else []
        per_row_tokens.append(tokens)
        for index, token in enumerate(tokens):
            row_ids.append(row_id)
            token_indexes.append(index)
            is_full_cell.append(False)
            key_inputs.append(token)
        row_ids.append(row_id)
        token_indexes.append(_FULL_CELL_INDEX)
        is_full_cell.append(True)
        key_inputs.append(cell)

    candidates = pl.DataFrame(
        {
            "row_id": pl.Series("row_id", row_ids, dtype=pl.Int64),
            _TOKEN_INDEX: pl.Series(_TOKEN_INDEX, token_indexes, dtype=pl.Int64),
            _IS_FULL_CELL: pl.Series(_IS_FULL_CELL, is_full_cell, dtype=pl.Boolean),
            "source_key": encode_rule_match_key(
                pl.Series(key_inputs, dtype=pl.String), apply_normalization=apply_normalization
            ),
        }
    )
    return candidates, per_row_tokens


def _apply_source_rewrite(
    dataset: pl.DataFrame,
    joined: pl.DataFrame,
    source_update_mask: pl.Series,
    source_column: str,
    source_pre: pl.Series,
    per_row_tokens: list[list[str]],
) -> tuple[pl.DataFrame, int]:
    """Substitute matched source tokens, preserving the rest, then rebuild each cell.

    A token match replaces just that token and leaves its siblings intact; an ``#EXACT#`` match
    replaces the whole cell. Where several rules hit the same token, the last in join order wins.
    Each rebuilt cell is canonicalized, so the result is deduplicated and sorted.

    The change count is the number of rows whose stored cell text actually changed.
    """
    if not bool(source_update_mask.any()):
        return dataset, 0

    updates = joined.filter(source_update_mask).select(
        "row_id", _TOKEN_INDEX, "value_source_result"
    )
    token_substitutions: dict[int, dict[int, str | None]] = {}
    full_cell_overrides: dict[int, str | None] = {}
    for row_id, token_index, value in updates.iter_rows():
        if token_index == _FULL_CELL_INDEX:
            full_cell_overrides[row_id] = value
        else:
            token_substitutions.setdefault(row_id, {})[token_index] = value

    affected = sorted({*token_substitutions, *full_cell_overrides})
    new_values: list[str | None] = []
    for row_id in affected:
        if row_id in full_cell_overrides:
            new_values.append(canonicalize_token_cell(full_cell_overrides[row_id]))
            continue
        substitutions = token_substitutions[row_id]
        rebuilt = [
            substitutions.get(index, token)
            for index, token in enumerate(per_row_tokens[row_id - 1])
        ]
        kept = [token for token in rebuilt if token is not None]
        new_values.append(canonicalize_token_cell(_TOKEN_DELIMITER.join(kept)))

    indexes = [row_id - 1 for row_id in affected]
    before = source_pre.gather(indexes)
    new_dataset = _scatter_column(
        dataset, source_column, indexes, pl.Series(new_values, dtype=pl.String)
    )
    after = new_dataset.get_column(source_column).gather(indexes)
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
    # Null-safe join: polars does not match null to null, so fold null keys to a sentinel.
    audit_key = list(_AUDIT_KEY)
    fold_names = [f"__audit_key_{index}__" for index in range(len(audit_key))]
    folded_counts = matched_counts.with_columns(
        pl.col(key).cast(pl.String).fill_null(_AUDIT_NA_SENTINEL).alias(fold)
        for key, fold in zip(audit_key, fold_names, strict=True)
    )
    folded_rules = normalize_rules.with_columns(
        pl.col(key).cast(pl.String).fill_null(_AUDIT_NA_SENTINEL).alias(fold)
        for key, fold in zip(audit_key, fold_names, strict=True)
    )
    return (
        folded_counts.join(folded_rules, on=fold_names, how="left")
        .drop(fold_names)
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
