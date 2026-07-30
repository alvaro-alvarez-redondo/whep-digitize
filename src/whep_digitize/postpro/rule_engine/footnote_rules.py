"""Apply footnote-sourced rules with split / match / reconstruct semantics.

The Python port of ``r/2-postpro_pipeline/23-postpro_rule_engine/23-footnote-rules.R``
(``apply_footnote_rules``) — the hardest single module in the rule engine. For rules whose
``column_source == "footnotes"`` it:

1. splits each row's ``;``-delimited footnotes into long tokens (R ``strsplit`` semantics:
   ``NA`` -> one ``NA`` token, ``""`` -> zero tokens, a trailing empty field is dropped);
2. cartesian-joins each footnote token to the rules on the source match key;
3. for rules that target a data column, keeps the match only when the current target value also
   satisfies the rule's target condition;
4. resolves each ``(row_id, footnote_index)`` token across cartesian duplicates with the
   precedence **remove > replace > original** (first replacement in join order wins);
5. reconstructs the footnotes column in ``footnote_index`` order (``;``-joined, ``NA`` tokens
   dropped, all-``NA`` / empty rows -> ``NA``);
6. applies target-column updates via :func:`apply_target_updates_with_strategy`;
7. reports the footnote-text change count against a snapshot **before-image** and the changed
   columns (``"footnotes"`` only when the footnote text actually changed, plus each mutated
   target column), and emits a per-rule audit table.

R mutates ``dataset_df`` in place; this port is functional and returns the updated frame in
:class:`FootnoteRulesResult`.
"""

from __future__ import annotations

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
from whep_digitize.setup.helpers.assertions import require

# R ``trimws()`` default whitespace class is ``[ \t\r\n]``; match it exactly.
_R_TRIMWS_CHARS = " \t\r\n"
_RULE_ORDER = "__whep_rule_order__"
_MATCHED = "__whep_matched__"
_AUDIT_KEY = (
    "value_source_raw",
    "value_source_result",
    "column_target",
    "value_target_raw",
    "value_target_result",
)


@dataclass(frozen=True, slots=True)
class FootnoteRulesResult:
    """Result of applying footnote rules (R ``list(data, audit, ...)``).

    Attributes:
        data: The updated dataset (R mutated its argument in place; this port returns it).
        audit: One row per applied rule effect (empty when nothing changed).
        overwrite_events: Last-rule-wins overwrite diagnostics from the target updates.
        changed_value_count: Total target + footnote-text cell changes.
        changed_columns: Columns whose stored values actually changed.
    """

    data: pl.DataFrame
    audit: pl.DataFrame
    overwrite_events: pl.DataFrame
    changed_value_count: int
    changed_columns: tuple[str, ...]


def _r_strsplit(cell: str | None) -> list[str | None]:
    """Split ``cell`` on ``;`` with R ``strsplit(x, ";", fixed = TRUE)`` semantics."""
    if cell is None:
        return [None]
    if cell == "":
        return []
    parts: list[str | None] = list(cell.split(";"))
    if parts and parts[-1] == "":
        parts = parts[:-1]  # R drops the trailing empty field
    return parts


def _explode_footnotes(footnotes: pl.Series) -> pl.DataFrame:
    """Explode the footnotes column into one row per ``;`` token (R long format)."""
    row_ids: list[int] = []
    raws: list[str | None] = []
    indices: list[int] = []
    tokens: list[str | None] = []
    for row_id, cell in enumerate(footnotes.to_list(), start=1):
        for index, raw in enumerate(_r_strsplit(cell), start=1):
            row_ids.append(row_id)
            raws.append(raw)
            indices.append(index)
            stripped = None if raw is None else raw.strip(_R_TRIMWS_CHARS)
            tokens.append(stripped if stripped else None)
    return pl.DataFrame(
        {
            "row_id": pl.Series("row_id", row_ids, dtype=pl.Int64),
            "footnote_raw": pl.Series("footnote_raw", raws, dtype=pl.String),
            "footnote_index": pl.Series("footnote_index", indices, dtype=pl.Int64),
            "footnote": pl.Series("footnote", tokens, dtype=pl.String),
        }
    )


def _build_normalize_rules(
    rules: pl.DataFrame,
    *,
    source_value_column: str,
    target_value_column: str,
    footnote_normalization: bool,
) -> pl.DataFrame:
    """Build the deduplicated, keyed footnote-rule table (R ``normalize_rules``)."""
    value_source_raw = rules.get_column("value_source_raw")
    normalize_rules = pl.DataFrame(
        {
            "column_source": pl.Series(
                "column_source", ["footnotes"] * rules.height, dtype=pl.String
            ),
            "value_source_raw": value_source_raw,
            "source_value_raw": rules.get_column(source_value_column),
            "column_target": rules.get_column("column_target"),
            "value_target_raw": rules.get_column("value_target_raw"),
            "value_target_result_encoded": encode_target_rule_value(
                rules.get_column(target_value_column)
            ),
            "source_key": encode_rule_match_key(
                value_source_raw, apply_normalization=footnote_normalization
            ),
        }
    ).unique(maintain_order=True)

    decoded_target = decode_target_rule_value(
        normalize_rules.get_column("value_target_result_encoded")
    ).rename("value_target_result")
    return (
        normalize_rules.with_columns(
            normalize_rules.get_column("source_value_raw")
            .cast(pl.String)
            .alias("value_source_result"),
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


def _refine_matched_by_condition(
    joined: pl.DataFrame,
    dataset: pl.DataFrame,
    matched: pl.Series,
    *,
    apply_match_normalization: bool,
    excluded_columns: tuple[str, ...],
    tokenized_columns: tuple[str, ...],
) -> pl.Series:
    """Keep conditional-target matches only when the current target value satisfies the rule."""
    column_target = joined.get_column("column_target")
    value_target_raw = joined.get_column("value_target_raw")
    conditional_target = matched & (column_target != "footnotes") & value_target_raw.is_not_null()
    if not bool(conditional_target.any()):
        return matched

    conditional_flags = conditional_target.to_list()
    target_columns = column_target.to_list()
    row_ids = joined.get_column("row_id").to_list()
    condition_values = value_target_raw.to_list()
    condition_match = [False] * joined.height
    distinct_targets = dict.fromkeys(
        target_columns[i] for i in range(joined.height) if conditional_flags[i]
    )
    for target_column in distinct_targets:
        positions = [
            i
            for i in range(joined.height)
            if conditional_flags[i] and target_columns[i] == target_column
        ]
        current = dataset.get_column(target_column).gather([row_ids[i] - 1 for i in positions])
        matches = match_rule_target_condition_values(
            current,
            pl.Series([condition_values[i] for i in positions], dtype=pl.String),
            tokenized_target=target_column in tokenized_columns,
            apply_match_normalization=apply_match_normalization
            and target_column not in excluded_columns,
        ).to_list()
        for position, matched_value in zip(positions, matches, strict=True):
            condition_match[position] = matched_value
    return matched & (~conditional_target | pl.Series(condition_match, dtype=pl.Boolean))


def _reconstruct_footnotes(joined: pl.DataFrame, n_rows: int) -> pl.Series:
    """Resolve tokens per ``(row_id, footnote_index)`` and rebuild the footnotes column."""
    token_resolution = (
        joined.group_by(["row_id", "footnote_index"], maintain_order=True)
        .agg(
            pl.col("is_remove").any().alias("any_remove"),
            pl.col("is_replace").any().alias("any_replace"),
            pl.col("footnote").first().alias("footnote"),
            pl.col("footnote_final")
            .filter(pl.col("is_replace"))
            .first()
            .alias("replacement_value"),
        )
        .with_columns(
            # Precedence: remove beats replace beats the original token.
            pl.when(pl.col("any_remove"))
            .then(pl.lit(None, dtype=pl.String))
            .when(pl.col("any_replace"))
            .then(pl.col("replacement_value"))
            .otherwise(pl.col("footnote"))
            .alias("footnote_final")
        )
        .sort(["row_id", "footnote_index"])
    )
    reconstructed = (
        token_resolution.filter(pl.col("footnote_final").is_not_null())
        .group_by("row_id", maintain_order=True)
        .agg(pl.col("footnote_final").str.join("; ").alias("footnotes_new"))
    )
    row_to_footnotes = dict(
        zip(
            reconstructed.get_column("row_id").to_list(),
            reconstructed.get_column("footnotes_new").to_list(),
            strict=True,
        )
    )
    return pl.Series(
        "footnotes",
        [row_to_footnotes.get(row_id) for row_id in range(1, n_rows + 1)],
        dtype=pl.String,
    )


def _build_audit(
    joined: pl.DataFrame,
    *,
    dataset_name: str,
    execution_timestamp_utc: str,
    rule_file_id: str,
    stage: str,
) -> pl.DataFrame:
    """Build the per-rule audit table over matched, non-no-op token matches."""
    footnote = pl.col("footnote")
    footnote_final = pl.col("footnote_final")
    noop = pl.col(_MATCHED) & (
        (footnote.is_not_null() & footnote_final.is_not_null() & (footnote == footnote_final))
        | (footnote.is_null() & footnote_final.is_null())
    )
    audit_source = joined.filter(pl.col(_MATCHED) & ~noop)
    return (
        audit_source.group_by(list(_AUDIT_KEY), maintain_order=True)
        .agg(pl.len().alias("affected_rows"))
        .select(
            pl.lit(dataset_name).alias("dataset_name"),
            pl.lit("footnotes").alias("column_source"),
            "value_source_raw",
            "value_source_result",
            "column_target",
            "value_target_raw",
            "value_target_result",
            pl.col("affected_rows").cast(pl.Int64),
            pl.lit(execution_timestamp_utc).alias("execution_timestamp_utc"),
            pl.lit(rule_file_id).alias("rule_file_identifier"),
            pl.lit(stage).alias("execution_stage"),
        )
        .sort(
            ["column_source", "column_target", "value_source_raw", "value_target_raw"],
            nulls_last=True,
            maintain_order=True,
        )
    )


def apply_footnote_rules(
    dataset: pl.DataFrame,
    footnote_rules: pl.DataFrame,
    stage_name: str,
    dataset_name: str,
    rule_file_id: str,
    execution_timestamp_utc: str,
    *,
    apply_match_normalization: bool = True,
) -> FootnoteRulesResult:
    """Apply footnote-sourced rules to the dataset via split / match / reconstruct.

    Args:
        dataset: The dataset to update (returned updated; never mutated in place).
        footnote_rules: Rules whose ``column_source == "footnotes"`` (at least one row).
        stage_name: The execution stage (validated).
        dataset_name: Dataset identifier (for audit / overwrite events).
        rule_file_id: Rule file identifier (for audit / overwrite events).
        execution_timestamp_utc: Execution timestamp (for the audit table).
        apply_match_normalization: Whether to normalize match keys.

    Returns:
        A :class:`FootnoteRulesResult` with the updated dataset, audit, overwrite events, total
        change count, and the changed columns.

    Raises:
        ValidationError: If ``footnote_rules`` is empty or a required string argument is empty.
    """
    require(footnote_rules.height >= 1, "footnote_rules must have at least one row")
    stage = validate_postpro_stage_name(stage_name)
    require(len(dataset_name) >= 1, "dataset_name must be a non-empty string")
    require(len(rule_file_id) >= 1, "rule_file_id must be a non-empty string")
    require(len(execution_timestamp_utc) >= 1, "execution_timestamp_utc must be a non-empty string")

    source_value_column = get_stage_source_value_column(stage)
    target_value_column = get_stage_target_value_column(stage)
    excluded_columns = resolve_rule_match_normalization_settings().excluded_columns
    footnote_normalization = apply_match_normalization and "footnotes" not in excluded_columns

    if "footnotes" not in dataset.columns:
        dataset = dataset.with_columns(pl.lit(None, dtype=pl.String).alias("footnotes"))
    footnotes_before = dataset.get_column("footnotes")
    n_rows = dataset.height

    fn_long = _explode_footnotes(footnotes_before)
    fn_long = fn_long.with_columns(
        encode_rule_match_key(
            fn_long.get_column("footnote"), apply_normalization=footnote_normalization
        ).alias("source_key")
    )
    normalize_rules = _build_normalize_rules(
        footnote_rules,
        source_value_column=source_value_column,
        target_value_column=target_value_column,
        footnote_normalization=footnote_normalization,
    )
    tokenized_columns = resolve_tokenized_target_condition_columns(
        get_target_update_strategy_config()
    )

    joined = fn_long.join(normalize_rules, on="source_key", how="left").sort(
        ["row_id", "footnote_index", _RULE_ORDER], nulls_last=True, maintain_order=True
    )
    matched = _refine_matched_by_condition(
        joined,
        dataset,
        joined.get_column("column_source").is_not_null(),
        apply_match_normalization=apply_match_normalization,
        excluded_columns=excluded_columns,
        tokenized_columns=tokenized_columns,
    )
    joined = joined.with_columns(matched.alias(_MATCHED)).with_columns(
        (pl.col(_MATCHED) & pl.col("value_source_result").is_not_null()).alias("is_replace"),
        (pl.col(_MATCHED) & pl.col("value_source_result").is_null()).alias("is_remove"),
    )
    joined = joined.with_columns(
        pl.when(pl.col("is_replace"))
        .then(pl.col("value_source_result"))
        .when(pl.col("is_remove"))
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(pl.col("footnote"))
        .alias("footnote_final")
    )

    new_dataset, overwrite_events, target_changed_count, changed_target_columns = (
        _apply_target_updates(joined, dataset, stage, dataset_name, rule_file_id)
    )

    new_footnotes = _reconstruct_footnotes(joined, n_rows)
    new_dataset = new_dataset.with_columns(new_footnotes)
    footnote_changed_count = count_elementwise_value_changes(footnotes_before, new_footnotes)

    changed_columns: list[str] = []
    if footnote_changed_count > 0:
        changed_columns.append("footnotes")
    changed_columns.extend(changed_target_columns)

    audit = _build_audit(
        joined,
        dataset_name=dataset_name,
        execution_timestamp_utc=execution_timestamp_utc,
        rule_file_id=rule_file_id,
        stage=stage,
    )
    return FootnoteRulesResult(
        data=new_dataset,
        audit=audit,
        overwrite_events=overwrite_events,
        changed_value_count=target_changed_count + footnote_changed_count,
        changed_columns=tuple(changed_columns),
    )


def _apply_target_updates(
    joined: pl.DataFrame,
    dataset: pl.DataFrame,
    stage: str,
    dataset_name: str,
    rule_file_id: str,
) -> tuple[pl.DataFrame, pl.DataFrame, int, list[str]]:
    """Apply each matched target column (not ``footnotes``) via the target-update strategy."""
    target_updates = joined.filter(
        pl.col(_MATCHED) & (pl.col("column_target") != "footnotes")
    ).select("row_id", "footnote_index", "column_target", "value_target_raw", "value_target_result")

    new_dataset = dataset
    overwrite_tables: list[pl.DataFrame] = []
    total_changed = 0
    changed_columns: list[str] = []
    if target_updates.height == 0:
        return new_dataset, empty_last_rule_wins_overwrite_events_df(), 0, changed_columns

    for target_column in dict.fromkeys(target_updates.get_column("column_target").to_list()):
        result = apply_target_updates_with_strategy(
            new_dataset,
            target_updates.filter(pl.col("column_target") == target_column),
            target_column,
            row_id_column="row_id",
            value_column="value_target_result",
            condition_column="value_target_raw",
            order_columns=["row_id", "footnote_index"],
            dataset_name=dataset_name,
            execution_stage=stage,
            rule_file_identifier=rule_file_id,
            source_column="footnotes",
        )
        new_dataset = result.dataset
        if result.overwrite_events.height > 0:
            overwrite_tables.append(result.overwrite_events)
        if result.changed_value_count > 0:
            changed_columns.append(target_column)
        total_changed += result.changed_value_count

    overwrite_events = (
        pl.concat(overwrite_tables)
        if overwrite_tables
        else empty_last_rule_wins_overwrite_events_df()
    )
    return new_dataset, overwrite_events, total_changed, changed_columns
