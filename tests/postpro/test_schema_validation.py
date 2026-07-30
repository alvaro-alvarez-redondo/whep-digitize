"""Unit tests for post-processing stage definitions and rule-schema validation.

Ports of ``21-stage-definitions.R`` (:mod:`whep_digitize.postpro.utilities.stage_definitions`)
and ``23-schema-validation.R`` (:mod:`whep_digitize.postpro.rule_engine.schema_validation`).
Byte parity vs R is covered in ``tests/parity/test_schema_validation_parity.py``; these tests
pin the behavioral contract without needing R.
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.rule_engine.schema_validation import (
    build_conditional_rule_dictionary,
    check_type_compatibility,
    coerce_rule_schema,
    ensure_rule_referenced_columns,
    normalize_rule_values_for_validation,
    validate_canonical_rules,
)
from whep_digitize.postpro.utilities.stage_definitions import (
    get_canonical_rule_columns,
    get_postpro_stage_names,
    get_stage_source_value_column,
    get_stage_target_value_column,
    validate_postpro_stage_name,
)
from whep_digitize.setup.errors import ValidationError

_CANONICAL = (
    "column_source",
    "value_source_raw",
    "value_source",
    "column_target",
    "value_target_raw",
    "value_target",
)
_NA_PLACEHOLDER = "..NA_INTERNAL.."


def _rules(rows: dict[str, list[str | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in rows.items()}
    )


def _canonical_rules(rows: dict[str, list[str | None]]) -> pl.DataFrame:
    height = len(next(iter(rows.values())))
    filled = {column: rows.get(column, [None] * height) for column in _CANONICAL}
    return _rules(filled)


# --------------------------------------------------------------------------- stage definitions


def test_stage_definitions_constants() -> None:
    assert get_canonical_rule_columns() == _CANONICAL
    assert get_postpro_stage_names() == ("clean", "harmonize")
    assert get_stage_source_value_column("clean") == "value_source"
    assert get_stage_target_value_column("harmonize") == "value_target"


def test_validate_postpro_stage_name_accepts_supported() -> None:
    assert validate_postpro_stage_name("clean") == "clean"
    assert validate_postpro_stage_name("harmonize") == "harmonize"


def test_validate_postpro_stage_name_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        validate_postpro_stage_name("cleanup")


# --------------------------------------------------------------------------- coerce_rule_schema


def test_coerce_strips_prefix_and_orders_canonical() -> None:
    raw = _rules(
        {
            "clean_value_target": ["tonne"],
            "clean_column_source": ["commodity"],
            "clean_value_target_raw": ["t"],
            "clean_value_source": ["WHEAT"],
            "clean_column_target": ["unit"],
            "clean_value_source_raw": ["wheat"],
        }
    )
    coerced = coerce_rule_schema(raw, "clean", "rules.xlsx")
    assert coerced.columns == [*_CANONICAL, "source_value_column_present"]
    assert coerced.get_column("source_value_column_present").to_list() == [True]
    assert coerced.get_column("value_source").to_list() == ["WHEAT"]


def test_coerce_synthesizes_absent_value_source() -> None:
    raw = _rules(
        {
            "harmonize_column_source": ["polity"],
            "harmonize_value_source_raw": ["spain"],
            "harmonize_column_target": ["continent"],
            "harmonize_value_target_raw": ["eu"],
            "harmonize_value_target": ["europe"],
        }
    )
    coerced = coerce_rule_schema(raw, "harmonize", "rules.xlsx")
    assert coerced.get_column("source_value_column_present").to_list() == [False]
    assert coerced.get_column("value_source").to_list() == [None]


def test_coerce_duplicate_after_normalization_raises() -> None:
    raw = _rules({"clean_column_source": ["a"], "column_source": ["b"]})
    with pytest.raises(ValidationError):
        coerce_rule_schema(raw, "clean", "rules.xlsx")


def test_coerce_missing_required_column_raises() -> None:
    raw = _rules({"clean_column_source": ["commodity"]})
    with pytest.raises(ValidationError):
        coerce_rule_schema(raw, "clean", "rules.xlsx")


def test_coerce_unexpected_column_raises() -> None:
    raw = _canonical_rules({"column_source": ["a"]}).with_columns(pl.lit("x").alias("clean_extra"))
    with pytest.raises(ValidationError):
        coerce_rule_schema(raw, "clean", "rules.xlsx")


# ----------------------------------------------------------- normalize_rule_values_for_validation


def test_normalize_folds_blank_and_null_to_placeholder() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity"],
            "value_source_raw": ["", None],
            "column_target": ["unit", "unit"],
            "value_target_raw": ["  ", "t"],
        }
    )
    result = normalize_rule_values_for_validation(rules, "clean")
    assert result.allowed_na_columns == _CANONICAL[1:3] + _CANONICAL[4:6]
    assert result.rules_for_validation.get_column("value_source_raw").to_list() == [
        _NA_PLACEHOLDER,
        _NA_PLACEHOLDER,
    ]
    assert result.rules_for_validation.get_column("value_target_raw").to_list() == [
        _NA_PLACEHOLDER,
        "t",
    ]


# --------------------------------------------------------------- ensure_rule_referenced_columns


def test_ensure_adds_missing_referenced_columns_as_null() -> None:
    dataset = pl.DataFrame({"commodity": pl.Series("commodity", ["x"], dtype=pl.String)})
    rules = _canonical_rules({"column_source": ["commodity"], "column_target": ["unit"]})
    result = ensure_rule_referenced_columns(dataset, rules)
    assert result.columns == ["commodity", "unit"]
    assert result.get_column("unit").to_list() == [None]


def test_ensure_is_noop_for_empty_rules() -> None:
    dataset = pl.DataFrame({"commodity": pl.Series("commodity", ["x"], dtype=pl.String)})
    empty = _canonical_rules({"column_source": []})
    result = ensure_rule_referenced_columns(dataset, empty)
    assert result.columns == ["commodity"]


# Note: R's duplicate-dataset-column guard cannot be exercised here — polars forbids duplicate
# column names at construction, so a duplicate-column frame is unconstructable (the guard is a
# faithful but structurally-unreachable mirror of the data.table check).


# --------------------------------------------------------------------------- type compatibility


def test_type_compatibility_string_column_imposes_no_constraint() -> None:
    dataset_column = pl.Series("commodity", ["a"], dtype=pl.String)
    # A non-numeric rule value is fine against a string column.
    check_type_compatibility(dataset_column, pl.Series(["not-a-number"]), "value_source_raw", "r")


def test_type_compatibility_numeric_column_accepts_numeric_values() -> None:
    dataset_column = pl.Series("count", [1, 2], dtype=pl.Int64)
    check_type_compatibility(dataset_column, pl.Series(["10", "20"]), "value_source_raw", "r")


def test_type_compatibility_numeric_column_rejects_non_numeric() -> None:
    dataset_column = pl.Series("count", [1, 2], dtype=pl.Int64)
    with pytest.raises(ValidationError):
        check_type_compatibility(dataset_column, pl.Series(["10", "abc"]), "value_source_raw", "r")


def test_type_compatibility_ignores_missing_rule_values() -> None:
    dataset_column = pl.Series("count", [1], dtype=pl.Int64)
    check_type_compatibility(dataset_column, pl.Series([None, None], dtype=pl.String), "f", "r")


# ----------------------------------------------------------------------- validate_canonical_rules


def _valid_dataset() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "commodity": pl.Series("commodity", ["x"], dtype=pl.String),
            "unit": pl.Series("unit", ["y"], dtype=pl.String),
        }
    )


def test_validate_passes_for_valid_rules() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity"],
            "value_source_raw": ["wheat", "rice"],
            "column_target": ["unit", "unit"],
            "value_target_raw": ["t", "kg"],
            "value_target": ["tonne", "kilo"],
        }
    )
    validate_canonical_rules(rules, _valid_dataset(), "rules.xlsx", "clean")


def test_validate_empty_rules_is_noop() -> None:
    validate_canonical_rules(
        _canonical_rules({"column_source": []}), _valid_dataset(), "r", "clean"
    )


def test_validate_missing_canonical_column_raises() -> None:
    rules = _rules({"column_source": ["commodity"]})
    with pytest.raises(ValidationError):
        validate_canonical_rules(rules, _valid_dataset(), "rules.xlsx", "clean")


def test_validate_null_required_column_raises() -> None:
    rules = _canonical_rules(
        {
            "column_source": [None],
            "value_source_raw": ["wheat"],
            "column_target": ["unit"],
            "value_target_raw": ["t"],
            "value_target": ["tonne"],
        }
    )
    with pytest.raises(ValidationError):
        validate_canonical_rules(rules, _valid_dataset(), "rules.xlsx", "clean")


def test_validate_missing_dataset_column_raises() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity"],
            "value_source_raw": ["wheat"],
            "column_target": ["nonexistent"],
            "value_target_raw": ["t"],
            "value_target": ["tonne"],
        }
    )
    with pytest.raises(ValidationError):
        validate_canonical_rules(rules, _valid_dataset(), "rules.xlsx", "clean")


def test_validate_duplicate_key_raises() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity"],
            "value_source_raw": ["wheat", "wheat"],
            "column_target": ["unit", "unit"],
            "value_target_raw": ["t", "t"],
            "value_target": ["tonne", "OTHER"],
        }
    )
    with pytest.raises(ValidationError):
        validate_canonical_rules(rules, _valid_dataset(), "rules.xlsx", "clean")


# --------------------------------------------------------------- build_conditional_rule_dictionary


def test_dictionary_empty_rules_returns_empty_list() -> None:
    assert build_conditional_rule_dictionary(_canonical_rules({"column_source": []}), "clean") == []


def test_dictionary_groups_and_orders_by_code_point() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity", "commodity", "polity"],
            "value_source_raw": ["b", "a", "Z", "p"],
            "column_target": ["unit", "unit", "unit", "unit"],
            "value_target_raw": [None, None, None, None],
            "value_target": ["v1", "v2", "v3", "v4"],
        }
    )
    groups = build_conditional_rule_dictionary(rules, "clean")
    assert len(groups) == 2
    # (column_target, column_source) order -> (commodity, unit) before (polity, unit).
    commodity_group, polity_group = groups
    assert commodity_group.get_column("column_source").to_list() == ["commodity"] * 3
    # Code-point order within group: "Z" (0x5A) < "a" (0x61) < "b" (0x62).
    assert commodity_group.get_column("value_source_raw").to_list() == ["Z", "a", "b"]
    assert polity_group.get_column("column_source").to_list() == ["polity"]


def test_dictionary_orders_nulls_last() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity"],
            "value_source_raw": [None, "a"],
            "column_target": ["unit", "unit"],
            "value_target_raw": ["t", "t"],
            "value_target": ["v1", "v2"],
        }
    )
    (group,) = build_conditional_rule_dictionary(rules, "clean")
    assert group.get_column("value_source_raw").to_list() == ["a", None]


def test_dictionary_drops_rows_with_null_group_columns() -> None:
    rules = _canonical_rules(
        {
            "column_source": ["commodity", None],
            "value_source_raw": ["a", "b"],
            "column_target": ["unit", "unit"],
            "value_target_raw": ["t", "t"],
            "value_target": ["v1", "v2"],
        }
    )
    groups = build_conditional_rule_dictionary(rules, "clean")
    assert len(groups) == 1
    assert groups[0].get_column("value_source_raw").to_list() == ["a"]
