"""Rule-schema coercion, canonical validation, and conditional dictionary construction.

The Python port of ``r/2-postpro_pipeline/23-postpro_rule_engine/23-schema-validation.R``.
Four responsibilities:

* :func:`coerce_rule_schema` — strip the stage prefix (``clean_`` / ``harmonize_``) from a rule
  file's columns, enforce the six canonical columns (``value_source`` optional, synthesized as
  null when absent), and carry a ``source_value_column_present`` flag.
* :func:`validate_canonical_rules` — schema completeness, required-value presence, dataset-column
  presence, rule-key uniqueness, conflict-free mappings, and rule/dataset type compatibility.
* :func:`build_conditional_rule_dictionary` — group rules by ``(column_source, column_target)``
  and order them by Unicode code point (the C-locale radix order R pins for portable
  ``last_rule_wins``; parity risk #7). Group order reproduces R's ``interaction`` factor order.
* Supporting helpers: :func:`normalize_rule_values_for_validation` (blank/NA ->
  ``na_placeholder`` for grouping), :func:`ensure_rule_referenced_columns`, and
  :func:`check_type_compatibility`.

R mutates ``dataset_df`` by reference; this port is functional and returns new frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

import polars as pl

from whep_digitize.postpro.utilities.stage_definitions import (
    get_canonical_rule_columns,
    get_stage_source_value_column,
    get_stage_target_value_column,
    validate_postpro_stage_name,
)
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require

_CONSTANTS = get_pipeline_constants()
_NA_PLACEHOLDER = _CONSTANTS.na_placeholder
# R ``trimws()`` default whitespace class is ``[ \t\r\n]``; match it exactly.
_R_TRIMWS_CHARS = " \t\r\n"
# Value columns whose blank/NA is permitted (folded to na_placeholder for validation grouping).
_ALLOWED_NA_VALUE_COLUMNS = (
    "value_source_raw",
    "value_source",
    "value_target_raw",
    "value_target",
)
# The rule-uniqueness key (source/target column + raw source/target value).
_UNIQUENESS_KEY = (
    "column_source",
    "value_source_raw",
    "column_target",
    "value_target_raw",
)


@dataclass(frozen=True, slots=True)
class RulesForValidation:
    """Rules prepared for validation grouping (R ``normalize_rule_values_for_validation``).

    Attributes:
        rules_for_validation: Rules with blank/NA folded to ``na_placeholder`` in the value
            columns (so missing keys group together deterministically).
        allowed_na_columns: The value columns present in the rules (those permitted to be blank).
    """

    rules_for_validation: pl.DataFrame
    allowed_na_columns: tuple[str, ...]


_T = TypeVar("_T")


def _unique_preserving_order(values: Sequence[_T]) -> list[_T]:
    """Return ``values`` deduplicated, preserving first-appearance order (R ``unique``)."""
    return list(dict.fromkeys(values))


def coerce_rule_schema(
    rule_df: pl.DataFrame,
    stage_name: str,
    rule_file_id: str,
    rule_file_path: str | None = None,
) -> pl.DataFrame:
    """Coerce a rule table to the canonical schema, stripping the stage prefix.

    Args:
        rule_df: The raw rule table (columns may carry a ``clean_`` / ``harmonize_`` prefix).
        stage_name: The execution stage (validated).
        rule_file_id: Rule file identifier (for error messages).
        rule_file_path: Rule file path (for error messages); defaults to ``rule_file_id``.

    Returns:
        The canonical rule table: the six canonical columns in order plus a boolean
        ``source_value_column_present`` flag (``value_source`` is synthesized as null if absent).

    Raises:
        ValidationError: On duplicate columns after prefix normalization, missing required
            columns, or unexpected columns.
    """
    require(len(rule_file_id) >= 1, "rule_file_id must be a non-empty string")
    resolved_path = rule_file_path if rule_file_path is not None else rule_file_id
    require(len(resolved_path) >= 1, "rule_file_path must be a non-empty string")
    stage = validate_postpro_stage_name(stage_name)

    canonical_columns = get_canonical_rule_columns()
    prefix = f"{stage}_"
    available = rule_df.columns
    normalized = [column.removeprefix(prefix) for column in available]

    duplicated = _duplicated_values(normalized)
    if duplicated:
        raise ValidationError(
            f"Rule file {rule_file_id} contains duplicate columns after stage-prefix "
            f"normalization: {', '.join(duplicated)}"
        )

    frame = rule_df.rename(
        {old: new for old, new in zip(available, normalized, strict=True) if old != new}
    )
    available = frame.columns

    source_result_column = get_stage_source_value_column(stage)
    source_value_column_present = source_result_column in available
    optional_columns = {source_result_column}

    missing_required = [
        column
        for column in canonical_columns
        if column not in available and column not in optional_columns
    ]
    if missing_required:
        raise ValidationError(
            f"Missing required columns in rule file {rule_file_id}: "
            f"{', '.join(missing_required)} (location: {resolved_path}; stage: {stage})"
        )

    unexpected = [column for column in available if column not in canonical_columns]
    if unexpected:
        raise ValidationError(
            f"Rule file {rule_file_id} contains unexpected columns: {', '.join(unexpected)}"
        )

    if source_result_column not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias(source_result_column))

    return frame.select(list(canonical_columns)).with_columns(
        pl.lit(source_value_column_present).alias("source_value_column_present")
    )


def normalize_rule_values_for_validation(
    rules_df: pl.DataFrame,
    stage_name: str,
    na_placeholder: str = _NA_PLACEHOLDER,
) -> RulesForValidation:
    """Fold blank/NA rule values to an internal placeholder for validation grouping.

    Args:
        rules_df: Canonical rule table.
        stage_name: The execution stage (validated).
        na_placeholder: The internal missing-value token.

    Returns:
        The prepared rules and the list of value columns that were present.
    """
    validate_postpro_stage_name(stage_name)
    require(len(na_placeholder) >= 1, "na_placeholder must be a non-empty string")

    allowed_na_columns = tuple(
        column for column in _ALLOWED_NA_VALUE_COLUMNS if column in rules_df.columns
    )
    replacements = [
        pl.when(
            pl.col(column).is_null()
            | (pl.col(column).str.strip_chars(_R_TRIMWS_CHARS).str.len_chars() == 0)
        )
        .then(pl.lit(na_placeholder))
        .otherwise(pl.col(column))
        .alias(column)
        for column in allowed_na_columns
        if rules_df.schema[column] == pl.String
    ]
    prepared = rules_df.with_columns(replacements) if replacements else rules_df
    return RulesForValidation(prepared, allowed_na_columns)


def ensure_rule_referenced_columns(
    dataset_df: pl.DataFrame, rules_df: pl.DataFrame
) -> pl.DataFrame:
    """Add any rule-referenced source/target columns missing from the dataset, as null.

    Args:
        dataset_df: The dataset (returned with any missing referenced columns added).
        rules_df: Canonical rule table.

    Returns:
        The dataset with missing ``column_source`` / ``column_target`` columns initialized to null.

    Raises:
        ValidationError: If the dataset already contains duplicate column names.
    """
    existing_columns = dataset_df.columns
    # A faithful mirror of the R guard. polars forbids duplicate column names at construction,
    # so this is structurally unreachable for a valid frame (kept for parity with data.table).
    duplicated = _duplicated_values(existing_columns)
    if duplicated:
        raise ValidationError(
            "dataset contains duplicate column names before rule-column materialization: "
            f"{', '.join(duplicated)}"
        )

    if rules_df.height == 0:
        return dataset_df

    # R applies unique() to the raw values, then trims, then drops NA/empty (this order).
    referenced_raw: list[str | None] = []
    for column in ("column_source", "column_target"):
        if column in rules_df.columns:
            referenced_raw.extend(rules_df.get_column(column).cast(pl.String).to_list())

    trimmed = [None if value is None else value.strip(_R_TRIMWS_CHARS) for value in referenced_raw]
    referenced = [value for value in _unique_preserving_order(trimmed) if value]

    missing_columns = _unique_preserving_order(
        [column for column in referenced if column not in existing_columns]
    )
    if not missing_columns:
        return dataset_df
    return dataset_df.with_columns(
        [pl.lit(None, dtype=pl.String).alias(column) for column in missing_columns]
    )


def check_type_compatibility(
    dataset_column: pl.Series,
    rule_values: pl.Series,
    field_name: str,
    rule_file_id: str,
    column_name: str = "unknown",
    rule_file_path: str | None = None,
) -> None:
    """Validate that rule values can be cast to the dataset column's type.

    Only numeric / integer / Date dataset columns are checked; string columns (the norm in the
    all-text pipeline) impose no constraint, matching R.

    Args:
        dataset_column: The dataset column the rule values target.
        rule_values: The rule values to check.
        field_name: The rule field being checked (for error messages).
        rule_file_id: Rule file identifier (for error messages).
        column_name: The dataset column name (for error messages).
        rule_file_path: Rule file path (for error messages); defaults to ``rule_file_id``.

    Raises:
        ValidationError: If any non-missing rule value cannot be cast to the column's type.
    """
    resolved_path = rule_file_path if rule_file_path is not None else rule_file_id
    non_missing = rule_values.drop_nulls()
    if non_missing.len() == 0:
        return

    dtype = dataset_column.dtype
    if dtype in (pl.String, pl.Categorical):
        return

    text_values = non_missing.cast(pl.String)
    if dtype.is_numeric():
        _assert_castable(
            text_values, pl.Float64, "numeric", field_name, column_name, rule_file_id, resolved_path
        )
    if dtype.is_integer():
        _assert_castable(
            text_values, pl.Int64, "integer", field_name, column_name, rule_file_id, resolved_path
        )
    if dtype == pl.Date:
        parsed = text_values.str.to_date(strict=False)
        if parsed.null_count() > 0:
            _raise_type_error(
                text_values, parsed, "Date", field_name, column_name, rule_file_id, resolved_path
            )


def validate_canonical_rules(
    rules_df: pl.DataFrame,
    dataset_df: pl.DataFrame,
    rule_file_id: str,
    stage_name: str,
    rule_file_path: str | None = None,
) -> None:
    """Validate canonical rules against the dataset.

    Checks schema completeness, required-value presence, dataset-column presence, rule-key
    uniqueness, conflict-free source/target mappings, and type compatibility. The uniqueness
    check (duplicate ``(column_source, value_source_raw, column_target, value_target_raw)`` keys)
    subsumes the target/source conflict checks — the latter are kept for structural parity with R.

    Args:
        rules_df: Canonical rule table.
        dataset_df: The dataset the rules apply to.
        rule_file_id: Rule file identifier (for error messages).
        stage_name: The execution stage (validated).
        rule_file_path: Rule file path (for error messages); defaults to ``rule_file_id``.

    Raises:
        ValidationError: On any schema, missing-value, missing-column, uniqueness, conflict, or
            type-compatibility failure.
    """
    require(len(rule_file_id) >= 1, "rule_file_id must be a non-empty string")
    resolved_path = rule_file_path if rule_file_path is not None else rule_file_id
    require(len(resolved_path) >= 1, "rule_file_path must be a non-empty string")
    stage = validate_postpro_stage_name(stage_name)

    required_columns = get_canonical_rule_columns()
    missing_rule_columns = [column for column in required_columns if column not in rules_df.columns]
    if missing_rule_columns:
        raise ValidationError(
            f"Canonical rule schema validation failed for {rule_file_id}: "
            f"{', '.join(missing_rule_columns)}"
        )

    if rules_df.height == 0:
        return

    context = normalize_rule_values_for_validation(rules_df, stage)
    rules_for_validation = context.rules_for_validation
    allowed_na_columns = context.allowed_na_columns

    strict_required = [column for column in required_columns if column not in allowed_na_columns]
    columns_with_na = [
        column for column in strict_required if rules_df.get_column(column).null_count() > 0
    ]
    if columns_with_na:
        raise ValidationError(
            f"Missing values in required columns: {', '.join(columns_with_na)} "
            f"(location: {resolved_path}; stage: {stage})"
        )

    _assert_referenced_columns_present(rules_df, dataset_df, rule_file_id, resolved_path)
    _assert_unique_and_conflict_free(rules_for_validation, stage, rule_file_id, resolved_path)
    _assert_type_compatibility(rules_df, dataset_df, stage, rule_file_id, resolved_path)


def build_conditional_rule_dictionary(
    rules_df: pl.DataFrame, stage_name: str
) -> list[pl.DataFrame]:
    """Group canonical rules by ``(column_source, column_target)`` in deterministic order.

    Rules are ordered by Unicode code point (C-locale radix, parity risk #7) on
    ``(column_source, column_target, value_source_raw, value_target_raw, value_target)`` — the
    within-group order that feeds ``last_rule_wins``. Group order reproduces R's
    ``interaction(column_source, column_target)`` factor order (the first factor varies fastest,
    i.e. sorted by ``(column_target, column_source)``); rows with a null source/target column are
    dropped, as R's ``split`` drops NA factor levels.

    Args:
        rules_df: Canonical rule table.
        stage_name: The execution stage (validated).

    Returns:
        One frame per present ``(column_source, column_target)`` group, in application order.
    """
    stage = validate_postpro_stage_name(stage_name)
    if rules_df.height == 0:
        return []

    target_value_column = get_stage_target_value_column(stage)
    sort_columns = [
        "column_source",
        "column_target",
        "value_source_raw",
        "value_target_raw",
        target_value_column,
    ]
    ordered_rules = rules_df.sort(sort_columns, nulls_last=True, maintain_order=True)

    present_groups = (
        ordered_rules.filter(
            pl.col("column_source").is_not_null() & pl.col("column_target").is_not_null()
        )
        .select("column_source", "column_target")
        .unique(maintain_order=True)
        .sort(["column_target", "column_source"], nulls_last=True)
    )
    return [
        ordered_rules.filter(
            (pl.col("column_source") == column_source) & (pl.col("column_target") == column_target)
        )
        for column_source, column_target in present_groups.iter_rows()
    ]


# --------------------------------------------------------------------------- private helpers


def _duplicated_values(values: Sequence[str]) -> list[str]:
    """Return the values that appear more than once, in first-duplicate order (R ``duplicated``)."""
    seen: set[str] = set()
    duplicated: list[str] = []
    for value in values:
        if value in seen and value not in duplicated:
            duplicated.append(value)
        seen.add(value)
    return duplicated


def _clean_unique_columns(series: pl.Series) -> list[str]:
    """Trim, unique, then drop NA/empty (R ``unique(trimws(as.character(x)))`` then filter)."""
    trimmed = [
        None if value is None else value.strip(_R_TRIMWS_CHARS)
        for value in series.cast(pl.String).to_list()
    ]
    return [value for value in _unique_preserving_order(trimmed) if value]


def _assert_referenced_columns_present(
    rules_df: pl.DataFrame, dataset_df: pl.DataFrame, rule_file_id: str, rule_file_path: str
) -> None:
    """Abort if any rule source/target column is absent from the dataset."""
    dataset_columns = set(dataset_df.columns)
    missing_source = [
        column
        for column in _clean_unique_columns(rules_df.get_column("column_source"))
        if column not in dataset_columns
    ]
    missing_target = [
        column
        for column in _clean_unique_columns(rules_df.get_column("column_target"))
        if column not in dataset_columns
    ]
    if missing_source or missing_target:
        raise ValidationError(
            f"Rule columns are not present in dataset for {rule_file_id}: "
            f"missing source columns: {', '.join(missing_source) or '(none)'}; "
            f"missing target columns: {', '.join(missing_target) or '(none)'} "
            f"(location: {rule_file_path})"
        )


def _assert_unique_and_conflict_free(
    rules_for_validation: pl.DataFrame, stage: str, rule_file_id: str, rule_file_path: str
) -> None:
    """Abort on duplicate rule keys or conflicting source/target mappings."""
    key = list(_UNIQUENESS_KEY)

    duplicate_keys = (
        rules_for_validation.group_by(key, maintain_order=True)
        .agg(pl.len().alias("row_count"))
        .filter(pl.col("row_count") > 1)
    )
    if duplicate_keys.height > 0:
        raise ValidationError(
            f"Rule uniqueness validation failed for {rule_file_id}: "
            f"{duplicate_keys.height} duplicate key(s) (location: {rule_file_path})"
        )

    # Kept for structural parity with R; unreachable once the uniqueness check passes (a key with
    # multiple distinct target/source values necessarily has >1 row).
    target_value_column = get_stage_target_value_column(stage)
    source_value_column = get_stage_source_value_column(stage)
    for value_column, message in (
        (target_value_column, "Conflicting rules detected"),
        (source_value_column, "Conflicting source rewrite rules detected"),
    ):
        conflict = (
            rules_for_validation.group_by(key, maintain_order=True)
            .agg(pl.col(value_column).n_unique().alias("distinct_count"))
            .filter(pl.col("distinct_count") > 1)
        )
        if conflict.height > 0:
            raise ValidationError(f"{message} in {rule_file_id}.")


def _assert_type_compatibility(
    rules_df: pl.DataFrame,
    dataset_df: pl.DataFrame,
    stage: str,
    rule_file_id: str,
    rule_file_path: str,
) -> None:
    """Check rule/dataset type compatibility for source, target, and source-result values."""
    dataset_columns = set(dataset_df.columns)
    source_value_column = get_stage_source_value_column(stage)

    _check_by_column(
        rules_df,
        "column_source",
        "value_source_raw",
        dataset_df,
        dataset_columns,
        rule_file_id,
        rule_file_path,
    )
    _check_by_column(
        rules_df,
        "column_target",
        "value_target_raw",
        dataset_df,
        dataset_columns,
        rule_file_id,
        rule_file_path,
    )
    rules_with_source_result = rules_df.filter(pl.col(source_value_column).is_not_null())
    if rules_with_source_result.height > 0:
        _check_by_column(
            rules_with_source_result,
            "column_source",
            source_value_column,
            dataset_df,
            dataset_columns,
            rule_file_id,
            rule_file_path,
        )


def _check_by_column(
    rules_df: pl.DataFrame,
    column_name_field: str,
    value_field: str,
    dataset_df: pl.DataFrame,
    dataset_columns: set[str],
    rule_file_id: str,
    rule_file_path: str,
) -> None:
    """Run :func:`check_type_compatibility` per distinct referenced column (R ``by = column``)."""
    for column in _unique_preserving_order(rules_df.get_column(column_name_field).to_list()):
        if column is None or column not in dataset_columns:
            continue
        group_values = rules_df.filter(pl.col(column_name_field) == column).get_column(value_field)
        check_type_compatibility(
            dataset_df.get_column(column),
            group_values,
            value_field,
            rule_file_id,
            column_name=column,
            rule_file_path=rule_file_path,
        )


def _assert_castable(
    text_values: pl.Series,
    dtype: type[pl.DataType],
    expected: str,
    field_name: str,
    column_name: str,
    rule_file_id: str,
    rule_file_path: str,
) -> None:
    """Abort if any value fails to cast to ``dtype``."""
    parsed = text_values.cast(dtype, strict=False)
    if parsed.null_count() > 0:
        _raise_type_error(
            text_values, parsed, expected, field_name, column_name, rule_file_id, rule_file_path
        )


def _raise_type_error(
    text_values: pl.Series,
    parsed: pl.Series,
    expected: str,
    field_name: str,
    column_name: str,
    rule_file_id: str,
    rule_file_path: str,
) -> None:
    """Raise a type-compatibility error listing the first few invalid values."""
    invalid_preview = text_values.filter(parsed.is_null()).to_list()[:5]
    raise ValidationError(
        f"Type compatibility validation failed for {rule_file_id}: expected {expected} for "
        f"column {column_name} (field {field_name}); invalid rule values (preview): "
        f"{', '.join(str(value) for value in invalid_preview)} (location: {rule_file_path})"
    )
