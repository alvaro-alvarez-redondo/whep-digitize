"""Unit tests for the unit-standardization core (rules setup + engine).

Covers rule preparation and the conversion engine
(:mod:`whep_digitize.postpro.standardize_units`). Byte parity vs the reference lives in
``tests/parity/test_standardize_parity.py``; these pin the behavioral contract,
covering conversion, offset, fallback, prefix fold, revert, and validation.
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.standardize_units.engine import (
    StandardizeResult,
    apply_standardize_rules,
)
from whep_digitize.postpro.standardize_units.rules_setup import (
    normalize_conversion_rule_columns,
    prepare_standardize_rules,
    validate_conversion_rules,
    validate_rule_schema,
)
from whep_digitize.setup.errors import ValidationError

_REQUIRED = ("commodity_key", "unit_source", "unit_target", "unit_factor", "unit_offset")


def _raw_rules(rows: list[tuple[str, str, str, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "commodity_key": pl.Series([row[0] for row in rows], dtype=pl.String),
            "unit_source": pl.Series([row[1] for row in rows], dtype=pl.String),
            "unit_target": pl.Series([row[2] for row in rows], dtype=pl.String),
            "unit_factor": pl.Series([row[3] for row in rows], dtype=pl.Float64),
            "unit_offset": pl.Series([row[4] for row in rows], dtype=pl.Float64),
        }
    )


def _prepared(rows: list[tuple[str, str, str, float, float]]) -> pl.DataFrame:
    return prepare_standardize_rules(_raw_rules(rows))


def _dataset(commodity: list[str], unit: list[str], value: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "commodity": pl.Series("commodity", commodity, dtype=pl.String),
            "unit": pl.Series("unit", unit, dtype=pl.String),
            "value": pl.Series("value", value, dtype=pl.String),
        }
    )


def _apply(dataset: pl.DataFrame, rules: pl.DataFrame) -> StandardizeResult:
    return apply_standardize_rules(dataset, rules, "unit", "value", "commodity")


# --------------------------------------------------------------------------- rules_setup


def test_validate_rule_schema_accepts_complete() -> None:
    validate_rule_schema(_raw_rules([("wheat", "kg", "g", 1000.0, 0.0)]), _REQUIRED, "test")


def test_validate_rule_schema_errors_missing_column() -> None:
    with pytest.raises(ValidationError, match="Missing required columns"):
        validate_rule_schema(pl.DataFrame({"commodity_key": ["wheat"]}), _REQUIRED, "test")


def test_validate_rule_schema_errors_on_null() -> None:
    rules = _raw_rules([("wheat", "kg", "g", 1000.0, 0.0)]).with_columns(
        pl.lit(None, dtype=pl.String).alias("commodity_key")
    )
    with pytest.raises(ValidationError, match="missing values"):
        validate_rule_schema(rules, _REQUIRED, "test")


def test_normalize_renames_legacy_columns() -> None:
    legacy = pl.DataFrame(
        {
            "commodity": ["wheat"],
            "from_unit": ["kg"],
            "to_unit": ["g"],
            "factor": [1000.0],
            "offset": [0.0],
        }
    )
    result = normalize_conversion_rule_columns(legacy)
    assert set(_REQUIRED).issubset(result.columns)


def test_normalize_preserves_modern_columns() -> None:
    modern = _raw_rules([("wheat", "kg", "g", 1000.0, 0.0)])
    assert normalize_conversion_rule_columns(modern).columns == list(modern.columns)


def test_normalize_rejects_colliding_aliases() -> None:
    colliding = pl.DataFrame(
        {
            "commodity_key": ["wheat"],
            "unit_source": ["kg"],
            "unit_target": ["tonne"],
            "multiplier": [0.001],
            "factor": [0.001],
            "unit_offset": [0.0],
        }
    )
    with pytest.raises(ValidationError, match="same canonical column"):
        normalize_conversion_rule_columns(colliding)


def test_validate_conversion_rules_accepts_valid() -> None:
    validate_conversion_rules(
        _raw_rules([("wheat", "kg", "g", 1000.0, 0.0), ("rice", "kg", "g", 1000.0, 0.0)])
    )


def test_validate_conversion_rules_rejects_case_variant_duplicate() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        validate_conversion_rules(
            _raw_rules([("Wheat", "kg", "tonne", 0.001, 0.0), ("wheat", "kg", "tonne", 0.001, 0.0)])
        )


def test_validate_conversion_rules_detects_chained() -> None:
    with pytest.raises(ValidationError, match="chained"):
        validate_conversion_rules(
            _raw_rules([("wheat", "kg", "g", 1000.0, 0.0), ("wheat", "g", "mg", 1000.0, 0.0)])
        )


def test_validate_conversion_rules_allows_chained_via_all_commodity() -> None:
    validate_conversion_rules(
        _raw_rules(
            [
                ("#ALL#", "kg", "g", 1000.0, 0.0),
                ("#ALL#", "g", "mg", 1000.0, 0.0),
                ("wheat", "kg", "g", 1000.0, 0.0),
            ]
        )
    )


def test_validate_conversion_rules_rejects_non_finite_factor() -> None:
    with pytest.raises(ValidationError, match="finite"):
        validate_conversion_rules(_raw_rules([("wheat", "kg", "g", float("inf"), 0.0)]))


def test_prepare_standardize_rules_materializes_keys() -> None:
    prepared = _prepared([("wheat", "kg", "g", 1000.0, 0.0)])
    for column in ("unit_factor_num", "unit_offset_num", "commodity_match_key", "unit_source_key"):
        assert column in prepared.columns


def test_prepare_standardize_rules_empty_input() -> None:
    assert prepare_standardize_rules(pl.DataFrame()).height == 0


# --------------------------------------------------------------------------- engine


def test_apply_converts_values() -> None:
    result = _apply(
        _dataset(["Wheat", "Rice"], ["kg", "kg"], ["2", "3"]),
        _prepared([("wheat", "kg", "g", 1000.0, 0.0)]),
    )
    assert result.matched_count == 1
    assert result.unmatched_count == 1
    assert result.data.get_column("value").to_list() == [2000.0, 3.0]
    assert result.data.get_column("unit").to_list() == ["g", "kg"]
    assert result.matched_rule_counts.get_column("affected_rows").to_list() == [1]


def test_apply_offset_conversion() -> None:
    result = _apply(
        _dataset(["temp"], ["celsius"], ["100"]),
        _prepared([("temp", "celsius", "fahrenheit", 1.8, 32.0)]),
    )
    assert result.data.get_column("value").to_list() == [212.0]
    assert result.data.get_column("unit").to_list() == ["fahrenheit"]


def test_apply_zero_rule_path() -> None:
    result = _apply(_dataset(["Wheat", "Rice"], ["kg", ""], ["2", ""]), pl.DataFrame())
    assert result.matched_count == 0
    assert result.unmatched_count == 1
    assert result.data.get_column("value").to_list() == [2.0, None]


def test_apply_errors_on_non_numeric_value() -> None:
    with pytest.raises(ValidationError, match="non-numeric"):
        _apply(_dataset(["Wheat"], ["kg"], ["not_numeric"]), pl.DataFrame())


def test_apply_uses_all_commodity_fallback() -> None:
    result = _apply(
        _dataset(["Wheat", "Corn", "Rice"], ["kg", "kg", "kg"], ["2", "3", "5"]),
        _prepared([("wheat", "kg", "g", 1000.0, 0.0), ("#ALL#", "kg", "g", 1000.0, 0.0)]),
    )
    assert result.matched_count == 3
    assert result.unmatched_count == 0
    assert result.data.get_column("value").to_list() == [2000.0, 3000.0, 5000.0]


def test_apply_fallback_attribution() -> None:
    result = _apply(
        _dataset(["Wheat", "Corn", "Rice"], ["kg", "kg", "kg"], ["2", "3", "5"]),
        _prepared([("wheat", "kg", "g", 1000.0, 0.0), ("#ALL#", "kg", "g", 1000.0, 0.0)]),
    )
    keyed = result.matched_rule_counts.sort(
        ["rule_commodity_match_key", "applied_commodity_match_key"]
    )
    assert keyed.get_column("rule_commodity_match_key").to_list() == [
        "all",
        "all",
        "wheat",
    ]
    assert keyed.get_column("applied_commodity_match_key").to_list() == ["corn", "rice", "wheat"]
    assert keyed.get_column("affected_rows").to_list() == [1, 1, 1]


def test_apply_prefers_specific_over_all_commodity_with_prefix() -> None:
    result = _apply(
        _dataset(["egg", "milk", "wheat"], ["1000 egg", "hectoliter", "kg"], ["2", "10", "5"]),
        _prepared(
            [
                ("egg", "1000 egg", "tonne", 0.0539, 0.0),
                ("#ALL#", "1000 egg", "tonne", 0.001, 0.0),
                ("#ALL#", "kg", "g", 1000.0, 0.0),
            ]
        ),
    )
    assert result.matched_count == 2
    assert result.data.get_column("value").to_list() == pytest.approx([2 * 0.0539, 10.0, 5000.0])
    assert result.data.get_column("unit").to_list() == ["tonne", "hectoliter", "g"]


def test_apply_does_not_strand_prefixed_unit_owned_by_another_commodity() -> None:
    result = _apply(
        _dataset(["chicken", "duck"], ["1000 egg", "1000 egg"], ["2", "3"]),
        _prepared(
            [
                ("chicken", "1000 egg", "tonne", 0.0539, 0.0),
                ("#ALL#", "egg", "tonne", 0.00005, 0.0),
            ]
        ),
    )
    assert result.matched_count == 2
    assert result.data.get_column("value").to_list() == pytest.approx(
        [2 * 0.0539, 3 * 1000 * 0.00005]
    )
    assert result.data.get_column("unit").to_list() == ["tonne", "tonne"]


def test_apply_reverts_prefixed_unit_matched_only_by_all_commodity() -> None:
    result = _apply(
        _dataset(["duck"], ["1000 egg"], ["3"]),
        _prepared([("#ALL#", "1000 egg", "tonne", 0.0539, 0.0)]),
    )
    assert result.matched_count == 1
    assert result.data.get_column("value").to_list() == pytest.approx([3 * 0.0539])
    assert result.data.get_column("unit").to_list() == ["tonne"]


def test_apply_missing_unit_column_raises() -> None:
    with pytest.raises(ValidationError, match="unit column"):
        apply_standardize_rules(
            pl.DataFrame({"value": ["1"]}), pl.DataFrame(), "unit", "value", "commodity"
        )
