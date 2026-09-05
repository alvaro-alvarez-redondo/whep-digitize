"""Apply one source->target conditional rule group.

``apply_conditional_rule_group`` (with ``prepare_conditional_rule_group``) applies one
``(column_source, column_target)`` rule group. For each group it:

1. builds deterministic match keys for each rule (source key, target-condition key, encoded
   target result);
2. explodes each source cell on ``;`` into one match candidate per token, plus one candidate for
   the whole cell, and cartesian-joins those candidates to the rules on the source key; a rule
   matches tokens by default and the whole cell only when marked ``#EXACT#``. Matched candidates
   are then kept only where the current target value satisfies the rule's target condition;
3. rewrites both **source** and **target** columns **symmetrically** — a matched token is
   substituted in place and its siblings are preserved, then the cell is rebuilt deduplicated
   and sorted.  ``#EXACT#`` rewrites the entire cell; ``#ANY#`` adds a new token.  Columns
   configured with the ``concatenate`` strategy (e.g. *notes*, *footnotes*) still use
   :func:`apply_target_updates_with_strategy` instead of token substitution.
4. emits a per-rule audit table and reports the changed columns **independently** — a group
   whose only effect was a source rewrite marks the source column, not the target.

``dataset_df`` is never mutated: the flow is functional and returns the updated frame in
:class:`ConditionalGroupResult`. The cartesian join is ordered by (dataset row, rule order) via an
explicit ``__rule_order__`` sort, which the source/target token-level last-rule-wins reductions
depend on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.rule_engine.matching_strategy import (
    decode_target_rule_value,
    encode_rule_match_key,
    encode_target_rule_value,
    resolve_rule_match_normalization_settings,
    resolve_target_update_strategy,
)
from whep_digitize.postpro.rule_engine.matching_values import (
    count_elementwise_value_changes,
    match_target_condition_token_map,
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
    split_token_cell,
)

# Cached constants (module-level, initialized once).
_CONSTANTS = get_pipeline_constants()

# The whitespace class trimmed from values: space, tab, CR, LF.
_TRIM_CHARS = " \t\r\n"
_TOKEN_DELIMITER = _CONSTANTS.postpro.target_update_strategies.concatenate_delimiter
_RULE_ORDER = "__whep_rule_order__"
_CURRENT_TARGET = "__whep_current_target__"
_TOKEN_INDEX = "__whep_token_index__"
_IS_FULL_CELL = "__whep_is_full_cell__"
_RULE_IS_EXACT = "__whep_rule_is_exact__"
# The character cells are tokenized on (mirrors ``split_token_cell``).
_TOKEN_SEPARATOR = ";"
# Internal column names used while exploding source candidates; prefixed so they can never
# collide with a dataset column.
_CELL = "__whep_cell__"
_TOKENS = "__whep_tokens__"
_KEY_RAW = "__whep_key_raw__"
# Token index reserved for the whole-cell candidate that #EXACT# rules match against.
_FULL_CELL_INDEX = -1
# Token index reserved for the wildcard candidate that #ANY# source rules match against.
_WILDCARD_SOURCE_INDEX = -2
# Raw sentinel used as the source_key for #ANY# source rules and wildcard candidates.
# This value is passed through encode_rule_match_key on both sides so the join key
# is identical regardless of the normalization setting.
_WILDCARD_SOURCE_KEY_RAW = "__whep_source_any_wildcard__"
_AUDIT_KEY = ("source_key", "target_key", "value_source_result", "value_target_result_encoded")
_AUDIT_ORDER = ("column_source", "column_target", "value_source_raw", "value_target_raw")
# Sentinel for null-safe joins: polars does not match null to null, so null audit keys are
# folded to this token before joining matched counts with normalize rules.
_AUDIT_NA_SENTINEL = _CONSTANTS.na_match_key


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
        changed_value_count: Total source + target cell changes.
        changed_columns: The columns actually changed (source and/or target), independently.
    """

    data: pl.DataFrame
    audit: pl.DataFrame
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
    # D10: a NULL source condition is inherently a full-cell condition — the only thing it can
    # mean is "this cell is NA" — so it is flagged exact and matches the full-cell candidate.
    # ``encode_rule_match_key`` folds both sides' nulls to the NA sentinel, so the key already
    # matches NA cells and only NA cells. Symmetric with the target side, where a NULL condition
    # matches NA only (D4). ``body`` is None only when the raw rule value was None: an
    # ``#EXACT#`` directive always resolves to a string body, never to None.
    rule_is_exact = pl.Series(
        _RULE_IS_EXACT,
        [is_exact or body is None for body, is_exact in resolved_source],
        dtype=pl.Boolean,
    )
    # D3: detect #ANY# in source values (case-insensitive, whitespace-tolerant).
    wildcard_casefold = _CONSTANTS.postpro.rule_match_wildcard_token.casefold()
    rule_is_source_wildcard = pl.Series(
        "__whep_rule_is_source_wildcard__",
        [
            (body or "").strip(_TRIM_CHARS).casefold() == wildcard_casefold
            for body, _ in resolved_source
        ],
        dtype=pl.Boolean,
    )
    # For #ANY# source rules, override the source_key to the wildcard sentinel so the
    # join matches the wildcard candidate emitted by _explode_source_candidates.
    # The sentinel is encoded through the same path as normal keys so the join key
    # is identical regardless of the normalization setting.
    wildcard_source_key = encode_rule_match_key(
        pl.Series([_WILDCARD_SOURCE_KEY_RAW], dtype=pl.String),
        apply_normalization=apply_source_norm,
    )[0]
    source_keys = encode_rule_match_key(
        source_match_values, apply_normalization=apply_source_norm
    )
    source_keys_list = source_keys.to_list()
    is_wildcard_list = rule_is_source_wildcard.to_list()
    for i in range(len(source_keys_list)):
        if is_wildcard_list[i]:
            source_keys_list[i] = wildcard_source_key
    source_keys_series = pl.Series("source_key", source_keys_list, dtype=pl.String)
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
            "__whep_rule_is_source_wildcard__": rule_is_source_wildcard,
            "source_key": source_keys_series,
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
        dataset_name: Dataset identifier (for the audit table).
        rule_file_id: Rule file identifier (for the audit table).
        execution_timestamp_utc: Execution timestamp (for the audit table).
        apply_match_normalization: Whether to normalize match keys.
        prepared_group: A prepared group (mutually exclusive with ``group_rules``).

    Returns:
        A :class:`ConditionalGroupResult` with the updated dataset, audit, total change count,
        and the independently-reported changed columns.

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
    # Each sentinel candidate costs one row per dataset row and is then multiplied by the rule
    # join, so only emit the ones some rule in this group can actually key against.
    group_has_wildcard_rule = bool(
        normalize_rules.get_column("__whep_rule_is_source_wildcard__").fill_null(False).any()
    )
    group_has_full_cell_rule = bool(
        normalize_rules.get_column(_RULE_IS_EXACT).fill_null(False).any()
    )
    join_candidates, per_row_tokens = _explode_source_candidates(
        source_pre,
        apply_normalization=apply_source_norm,
        emit_wildcard_candidate=group_has_wildcard_rule,
        emit_full_cell_candidate=group_has_full_cell_rule,
    )

    # Left join keeps every candidate and fans out on a multi-rule match. The
    # (row_id, token-index, rule-order) sort makes that order deterministic, which the
    # source/target last-rule-wins reductions rely on.
    joined = (
        join_candidates.join(normalize_rules, on="source_key", how="left")
        .sort(["row_id", _TOKEN_INDEX, _RULE_ORDER], nulls_last=True, maintain_order=True)
        .with_row_index("__joined_idx__")
    )
    # ``row_id`` is 1-based; shift it in the expression engine. Materializing the joined
    # row ids into a Python list to decrement them costs ~15x more on a multi-million-row join.
    current_target = target_pre.gather(joined.get_column("row_id") - 1)
    joined = joined.with_columns(current_target.alias(_CURRENT_TARGET))

    # A rule matches in exactly one mode: an ``#EXACT#`` rule against the full-cell candidate,
    # a ``#ANY#`` wildcard rule against the wildcard candidate, or a plain rule against each
    # exploded token.  Requiring the flags to agree keeps the three modes from ever matching
    # the same candidate.
    source_matched = joined.get_column("column_source").is_not_null() & (
        # Normal token match: not full-cell candidate AND not an exact rule
        # AND not a wildcard candidate matching a wildcard rule.
        (
            joined.get_column(_IS_FULL_CELL).not_()
            & joined.get_column(_RULE_IS_EXACT).fill_null(False).not_()
            & joined.get_column("__whep_rule_is_source_wildcard__")
            .fill_null(False)
            .not_()
            & (joined.get_column(_TOKEN_INDEX) != _WILDCARD_SOURCE_INDEX)
        )
        # #EXACT# match: full-cell candidate AND exact rule.
        | (
            joined.get_column(_IS_FULL_CELL)
            & joined.get_column(_RULE_IS_EXACT).fill_null(False)
        )
        # #ANY# wildcard match: wildcard candidate AND wildcard rule.
        | (
            (joined.get_column(_TOKEN_INDEX) == _WILDCARD_SOURCE_INDEX)
            & joined.get_column("__whep_rule_is_source_wildcard__").fill_null(False)
        )
    )
    # Computing the condition over every joined row and AND-ing with the source match is
    # equivalent to evaluating it on the matched subset: unmatched rows are masked out regardless.
    # Also collect matched tokens for symmetric target tokenization.
    target_condition_result = match_target_condition_token_map(
        joined.get_column(_CURRENT_TARGET),
        joined.get_column("value_target_raw"),
        apply_match_normalization=apply_target_norm,
    )
    target_condition = target_condition_result[0]
    matched_tokens_per_row = target_condition_result[1]
    matched_row_mask = source_matched & target_condition
    source_update_mask = matched_row_mask & joined.get_column(
        "source_value_column_present"
    ).fill_null(False)

    new_dataset = dataset
    source_changed = 0
    target_changed = 0

    if bool(matched_row_mask.any()):
        new_dataset, source_changed = _apply_source_rewrite(
            new_dataset, joined, source_update_mask, source_column, source_pre, per_row_tokens
        )

        # Resolve target update strategy: concatenate columns (notes, footnotes) still use the
        # legacy path; all other columns use symmetric token substitution.
        target_strategy = resolve_target_update_strategy(target_column)

        if target_strategy == "concatenate":
            # Legacy path for notes/footnotes: concatenate strategy.
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
            target_changed = target_result.changed_value_count
        else:
            # Symmetric token substitution (default for tokenized columns).
            # Tokenize only affected rows (lazy tokenization; see _apply_target_token_rewrite).
            new_dataset, target_changed = _apply_target_token_rewrite(
                new_dataset,
                joined,
                matched_row_mask,
                target_column,
                target_pre,
                matched_tokens_per_row,
            )

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
        changed_value_count=source_changed + target_changed,
        changed_columns=tuple(changed_columns),
    )


def _explode_source_candidates(
    source: pl.Series,
    *,
    apply_normalization: bool,
    emit_wildcard_candidate: bool = True,
    emit_full_cell_candidate: bool = True,
) -> tuple[pl.DataFrame, list[list[str]]]:
    """Build one match candidate per source token, plus the two sentinel candidates.

    Element-wise matching is the default, so every canonical token of the source cell is offered
    as a candidate. One extra candidate carries the full cell, which is what an ``#EXACT#`` rule
    matches against. A row with no tokens (null / blank cell) still gets its full-cell candidate,
    so exact rules can target missing values.

    Both sentinels cost one candidate row per dataset row each, and each one is then multiplied
    by the rule join. A sentinel no rule can key against is pure waste — it can never satisfy
    ``source_matched`` — so the caller suppresses it. Emitting it changes nothing but the cost.

    Args:
        source: The source column.
        apply_normalization: Whether match keys are normalized.
        emit_wildcard_candidate: Emit the ``#ANY#`` sentinel. Only a wildcard rule can key
            against it, so the caller passes ``False`` when the group holds none.
        emit_full_cell_candidate: Emit the full-cell candidate. Only an ``#EXACT#`` rule (or a
            NULL-source rule, which D10 flags exact) can match it, so the caller passes
            ``False`` when the group holds neither.

    Returns:
        ``(candidates, per_row_tokens)`` — the candidate frame and, per dataset row, its canonical
        token list (index-aligned with the candidates' ``token_index``).
    """
    frame = pl.DataFrame({_CELL: source.cast(pl.String)}).with_row_index("row_id", offset=1)
    frame = frame.with_columns(
        pl.col("row_id").cast(pl.Int64),
        # Vectorized mirror of ``split_token_cell``: split on ``;``, trim the same whitespace
        # class, drop empties, dedupe, sort. ``list.sort`` orders by UTF-8 byte order, which is
        # Unicode code-point order — the same order ``sorted()`` gives the scalar helper. A null
        # cell folds to "" and yields no tokens, matching ``split_token_cell(None) == []``.
        pl.col(_CELL)
        .fill_null("")
        .str.split(_TOKEN_SEPARATOR)
        .list.eval(pl.element().str.strip_chars(_TRIM_CHARS))
        .list.eval(pl.element().filter(pl.element().str.len_chars() > 0))
        .list.unique()
        .list.sort()
        .alias(_TOKENS),
    )
    per_row_tokens: list[list[str]] = frame.get_column(_TOKENS).to_list()

    # Build each row's candidates as two aligned list columns and explode them together, so the
    # emitted order is the per-row order the loop produced (tokens ascending, then the wildcard
    # sentinel, then the full-cell one) without needing a window function or a sort.
    # D3: the wildcard candidate is what #ANY# source rules match against, symmetrically to how
    # #ANY# works on the target condition side. Its raw sentinel is encoded below alongside the
    # normal token keys, so the join key matches the rule side.
    index_parts: list[pl.Expr] = [pl.int_ranges(0, pl.col(_TOKENS).list.len(), dtype=pl.Int64)]
    key_parts: list[pl.Expr] = [pl.col(_TOKENS)]
    if emit_wildcard_candidate:
        index_parts.append(pl.lit(_WILDCARD_SOURCE_INDEX, dtype=pl.Int64))
        key_parts.append(pl.lit(_WILDCARD_SOURCE_KEY_RAW, dtype=pl.String))
    if emit_full_cell_candidate:
        index_parts.append(pl.lit(_FULL_CELL_INDEX, dtype=pl.Int64))
        key_parts.append(pl.col(_CELL))

    # A cell with no tokens and no sentinel to emit contributes nothing; drop it before the
    # explode so the result never depends on ``empty_as_null``, whose default changes in
    # polars 2.0 (it is pinned below regardless).
    exploded = (
        frame.select(
            "row_id",
            pl.concat_list(index_parts).alias(_TOKEN_INDEX),
            pl.concat_list(key_parts).alias(_KEY_RAW),
        )
        .filter(pl.col(_TOKEN_INDEX).list.len() > 0)
        .explode([_TOKEN_INDEX, _KEY_RAW], empty_as_null=True)
    )
    token_index_series = exploded.get_column(_TOKEN_INDEX)

    candidates = pl.DataFrame(
        {
            "row_id": exploded.get_column("row_id"),
            _TOKEN_INDEX: token_index_series,
            _IS_FULL_CELL: (token_index_series == _FULL_CELL_INDEX).rename(_IS_FULL_CELL),
            "source_key": encode_rule_match_key(
                exploded.get_column(_KEY_RAW), apply_normalization=apply_normalization
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
        "row_id", _TOKEN_INDEX, "value_source_result",
        "__whep_rule_is_source_wildcard__",
    )
    token_substitutions: dict[int, dict[str, str | None]] = {}
    full_cell_overrides: dict[int, str | None] = {}
    add_tokens: dict[int, list[str]] = {}
    for row_id, token_index, value, is_source_wildcard in updates.iter_rows():
        if is_source_wildcard:
            # D3: #ANY# source adds the value as a new token (symmetric to target #ANY#).
            add_tokens.setdefault(row_id, []).append(value)
        elif token_index == _FULL_CELL_INDEX:
            full_cell_overrides[row_id] = value
        else:
            token_value = per_row_tokens[row_id - 1][token_index]
            token_substitutions.setdefault(row_id, {})[token_value] = value

    affected = sorted({*token_substitutions, *full_cell_overrides, *add_tokens})
    new_values: list[str | None] = []
    for row_id in affected:
        if row_id in full_cell_overrides:
            new_values.append(canonicalize_token_cell(full_cell_overrides[row_id]))
            continue
        substitutions = token_substitutions.get(row_id, {})
        tokens = per_row_tokens[row_id - 1]
        rebuilt: list[str | None]
        if substitutions:
            rebuilt = [substitutions.get(token, token) for token in tokens]
        else:
            rebuilt = list(tokens)
        tokens_to_add = add_tokens.get(row_id, [])
        if tokens_to_add:
            rebuilt.extend(tokens_to_add)
        kept = [t for t in rebuilt if t is not None]
        new_values.append(canonicalize_token_cell(_TOKEN_DELIMITER.join(kept)))

    indexes = [row_id - 1 for row_id in affected]
    before = source_pre.gather(indexes)
    new_dataset = _scatter_column(
        dataset, source_column, indexes, pl.Series(new_values, dtype=pl.String)
    )
    after = new_dataset.get_column(source_column).gather(indexes)
    return new_dataset, count_elementwise_value_changes(before, after)


def _apply_target_token_rewrite(
    dataset: pl.DataFrame,
    joined: pl.DataFrame,
    target_update_mask: pl.Series,
    target_column: str,
    target_pre: pl.Series,
    matched_tokens_per_row: list[list[str | None]],
) -> tuple[pl.DataFrame, int]:
    """Substitute matched target tokens, preserving the rest, then rebuild each cell.

    Symmetric counterpart to :func:`_apply_source_rewrite` but operates on the target column.
    A normal token match replaces just that token and leaves siblings intact; an ``#EXACT#``
    match replaces the whole cell; ``#ANY#`` adds the new value as an additional token.
    Where several rules hit the same token, the last in join order wins (D7).

    Tokenizes target cells lazily: only the affected rows are tokenized, avoiding an
    O(N) scan of the entire target column when only a few rows need updates.

    Args:
        dataset: The dataset to update (returned; never mutated in place).
        joined: The cartesian-joined candidate frame (already sorted by rule order).
            Must have a ``__joined_idx__`` column with the original row index
            (added via ``with_row_index`` before calling this function).
        target_update_mask: Boolean mask selecting rows where the target should be updated.
        target_column: The target column name in the dataset.
        target_pre: The target column values as of the start of the group, used as the
            baseline for the change count. Tokenization reads the live column from
            ``dataset`` instead, so a source rewrite on the same column is not discarded.
        matched_tokens_per_row: For each joined row (indexed by ``__joined_idx__``),
            which original tokens matched (from
            :func:`match_target_condition_token_map`).

    Returns:
        ``(updated_dataset, changed_count)`` — the updated frame and the number of rows
        whose target cell actually changed.
    """
    if not bool(target_update_mask.any()):
        return dataset, 0

    # Filter and select columns needed for the rewrite loop.
    # __joined_idx__ provides the original index into matched_tokens_per_row.
    # Note: _RULE_IS_EXACT (source-side #EXACT# flag) is intentionally excluded;
    # target rewrite strategy is determined solely by value_target_raw.
    updates = joined.filter(target_update_mask).select(
        "row_id", "__joined_idx__",
        "value_target_raw", "value_target_result",
    )

    # Pre-compute wildcard and exact flags from data (avoids index-mapping bugs
    # when joined is filtered).  The #ANY# check mirrors matching_values._is_wildcard.
    wildcard_casefold = _CONSTANTS.postpro.rule_match_wildcard_token.casefold()
    exact_token = _CONSTANTS.postpro.rule_match_exact_token
    raw_values = updates.get_column("value_target_raw").to_list()
    # D2: #EXACT# in value_target_raw triggers a full-cell override (symmetric to the
    # source-side #EXACT#), detected from data rather than from the source-side
    # _RULE_IS_EXACT flag. Resolve the directive with the shared helper, never with an
    # open-coded prefix test: the marker is whitespace- and case-tolerant, and
    # match_target_condition_token_map resolves it the same way. Any divergence between the
    # two silently turns a matched rule into a no-op.
    resolved_targets = [resolve_exact_match_directive(value, exact_token) for value in raw_values]
    is_target_exact = [is_exact for _, is_exact in resolved_targets]
    # The wildcard test runs on the resolved body, mirroring matching_values.
    is_wildcard = [
        body is not None and body.strip(_TRIM_CHARS).casefold() == wildcard_casefold
        for body, _ in resolved_targets
    ]

    full_cell_overrides: dict[int, str | None] = {}
    add_tokens: dict[int, list[str]] = {}
    token_substitutions: dict[int, dict[str, str | None]] = {}

    row_ids = updates.get_column("row_id").to_list()
    joined_idxs = updates.get_column("__joined_idx__").to_list()
    values = updates.get_column("value_target_result").to_list()

    for idx in range(len(row_ids)):
        row_id = row_ids[idx]
        original_joined_idx = joined_idxs[idx]
        if is_target_exact[idx]:
            # D2: #EXACT# in target condition rewrites the entire target cell.
            full_cell_overrides[row_id] = values[idx]
        elif is_wildcard[idx]:
            # D3: #ANY# adds the value as a new token.
            add_tokens.setdefault(row_id, []).append(values[idx])
        else:
            # D5: normal rule replaces the matching token by value.
            matched = matched_tokens_per_row[original_joined_idx]
            if matched:
                # None→None matches can't be token substitutions (no tokens exist).
                # They become full-cell overrides instead.
                none_match = any(t is None for t in matched)
                if none_match:
                    full_cell_overrides[row_id] = values[idx]
                else:
                    token_substitutions.setdefault(row_id, {})
                    for token in matched:
                        assert token is not None  # filtered above
                        token_substitutions[row_id][token] = values[idx]

    affected = sorted({*token_substitutions, *full_cell_overrides, *add_tokens})
    if not affected:
        return dataset, 0

    # Lazy tokenization: tokenize only affected rows.
    # Read the LIVE column out of ``dataset`` rather than the ``target_pre`` snapshot. The two
    # are identical whenever the source and target columns differ, but when a rule group names
    # the same column on both sides the source rewrite has already run and written into
    # ``dataset``; tokenizing the stale snapshot and scattering whole cells would silently
    # discard it. ``target_pre`` stays the baseline for the change count only.
    target_tokens_cache: dict[int, list[str]] = {}
    target_current_list = dataset.get_column(target_column).cast(pl.String).to_list()

    def _get_target_tokens(row_id: int) -> list[str]:
        tokens = target_tokens_cache.get(row_id)
        if tokens is None:
            tokens = split_token_cell(target_current_list[row_id - 1])
            target_tokens_cache[row_id] = tokens
        return tokens

    new_values: list[str | None] = []
    for row_id in affected:
        if row_id in full_cell_overrides:
            new_values.append(canonicalize_token_cell(full_cell_overrides[row_id]))
            continue

        substitutions = token_substitutions.get(row_id, {})
        tokens = _get_target_tokens(row_id)
        rebuilt: list[str | None]
        if substitutions:
            rebuilt = [substitutions.get(token, token) for token in tokens]
        else:
            rebuilt = list(tokens)
        tokens_to_add = add_tokens.get(row_id, [])
        if tokens_to_add:
            rebuilt.extend(tokens_to_add)
        kept = [t for t in rebuilt if t is not None]
        new_values.append(canonicalize_token_cell(_TOKEN_DELIMITER.join(kept)))

    indexes = [row_id - 1 for row_id in affected]
    before = target_pre.gather(indexes)
    new_dataset = _scatter_column(
        dataset, target_column, indexes, pl.Series(new_values, dtype=pl.String)
    )
    after = new_dataset.get_column(target_column).gather(indexes)
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
