"""Unit tests for standardize-units aggregation + orchestration.

Ports of ``24-standardize-aggregation.R`` and ``24-standardize-orchestration.R``
(:mod:`whep_digitize.postpro.standardize_units.aggregation` /
:mod:`~whep_digitize.postpro.standardize_units.orchestration`). Byte parity vs R for aggregation
+ the layer audit lives in ``tests/parity/test_standardize_agg_parity.py``; these mirror the R
testthat cases without needing R.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from openpyxl import Workbook

from whep_digitize.postpro.standardize_units.aggregation import (
    aggregate_standardized_rows,
    extract_aggregated_rows,
)
from whep_digitize.postpro.standardize_units.orchestration import (
    attach_standardize_diagnostics,
    build_standardize_layer_audit,
    ensure_standardize_template_exists,
    read_all_standardize_rule_files,
    read_standardize_rule_workbook,
    run_standardize_units_layer_batch,
)
from whep_digitize.postpro.standardize_units.rules_setup import prepare_standardize_rules
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError


def _s(values: list[str | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


def _f(values: list[float | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.Float64)


def _write_workbook(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    workbook = Workbook()
    for index, (name, rows) in enumerate(sheets.items()):
        sheet = workbook.active if index == 0 else workbook.create_sheet(name)
        sheet.title = name
        for row in rows:
            sheet.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


_RULE_HEADER: list[object] = [
    "commodity_key",
    "unit_source",
    "unit_target",
    "unit_factor",
    "unit_offset",
]


# --------------------------------------------------------------------------- aggregation


def test_aggregate_sums_duplicate_groups() -> None:
    frame = pl.DataFrame(
        {
            "commodity": _s(["wheat", "wheat", "rice"]),
            "unit": _s(["kg", "kg", "kg"]),
            "value": _f([10, 20, 5]),
        }
    )
    result = aggregate_standardized_rows(frame, "value")
    assert result.height == 2
    assert result.filter(pl.col("commodity") == "wheat").get_column("value").to_list() == [30.0]
    assert result.filter(pl.col("commodity") == "rice").get_column("value").to_list() == [5.0]


def test_aggregate_all_na_group_is_null() -> None:
    frame = pl.DataFrame(
        {"commodity": _s(["wheat", "wheat"]), "unit": _s(["kg", "kg"]), "value": _f([None, None])}
    )
    result = aggregate_standardized_rows(frame, "value")
    assert result.height == 1
    assert result.get_column("value").to_list() == [None]


def test_aggregate_partial_na_sums_non_null() -> None:
    frame = pl.DataFrame(
        {"commodity": _s(["wheat", "wheat"]), "unit": _s(["kg", "kg"]), "value": _f([10, None])}
    )
    assert aggregate_standardized_rows(frame, "value").get_column("value").to_list() == [10.0]


def test_aggregate_preserves_column_order() -> None:
    frame = pl.DataFrame(
        {"commodity": _s(["wheat", "wheat"]), "value": _f([10, 20]), "unit": _s(["kg", "kg"])}
    )
    assert aggregate_standardized_rows(frame, "value").columns == ["commodity", "value", "unit"]


def test_aggregate_skips_already_unique() -> None:
    frame = pl.DataFrame(
        {"commodity": _s(["wheat", "rice"]), "unit": _s(["kg", "kg"]), "value": _f([10, 5])}
    )
    assert aggregate_standardized_rows(frame, "value").equals(frame)


def test_aggregate_single_row_unchanged() -> None:
    frame = pl.DataFrame({"commodity": _s(["wheat"]), "unit": _s(["kg"]), "value": _f([42])})
    assert aggregate_standardized_rows(frame, "value").equals(frame)


def test_aggregate_only_value_column() -> None:
    result = aggregate_standardized_rows(pl.DataFrame({"value": _f([10, 20, 30])}), "value")
    assert result.height == 1
    assert result.get_column("value").to_list() == [60.0]


def test_aggregate_is_idempotent() -> None:
    frame = pl.DataFrame(
        {
            "commodity": _s(["wheat", "wheat", "rice"]),
            "unit": _s(["kg", "kg", "kg"]),
            "value": _f([10, 20, 5]),
        }
    )
    once = aggregate_standardized_rows(frame, "value")
    assert aggregate_standardized_rows(once, "value").equals(once)


def test_aggregate_missing_value_column_raises() -> None:
    with pytest.raises(ValidationError, match="not found"):
        aggregate_standardized_rows(pl.DataFrame({"commodity": _s(["wheat"])}), "value")


def test_extract_returns_only_duplicate_rows() -> None:
    frame = pl.DataFrame(
        {
            "commodity": _s(["wheat", "wheat", "rice"]),
            "unit": _s(["kg", "kg", "kg"]),
            "value": _f([10, 20, 5]),
        }
    )
    result = extract_aggregated_rows(frame, "value")
    assert result.height == 2
    assert result.get_column("commodity").unique().to_list() == ["wheat"]


def test_extract_empty_when_no_duplicates() -> None:
    frame = pl.DataFrame(
        {"commodity": _s(["wheat", "rice"]), "unit": _s(["kg", "kg"]), "value": _f([10, 5])}
    )
    result = extract_aggregated_rows(frame, "value")
    assert result.height == 0
    assert result.columns == ["commodity", "unit", "value"]


# --------------------------------------------------------------------------- audit


def _audit_rules() -> pl.DataFrame:
    return prepare_standardize_rules(
        pl.DataFrame(
            {
                "commodity_key": _s(["wheat", "all commodity"]),
                "unit_source": _s(["kg", "kg"]),
                "unit_target": _s(["g", "g"]),
                "unit_factor": _f([1000, 1000]),
                "unit_offset": _f([0, 0]),
                "source_rule_sheet": _s(["standardize_unit", "standardize_unit"]),
                "source_rule_file": _s(["rules.xlsx", "rules.xlsx"]),
            }
        )
    )


def _matched_counts() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "rule_commodity_match_key": _s(["wheat", "all commodity", "all commodity"]),
            "applied_commodity_match_key": _s(["wheat", "corn", "rice"]),
            "unit_source_key": _s(["kg", "kg", "kg"]),
            "affected_rows": pl.Series([1, 1, 1], dtype=pl.Int64),
            "source_unit_raw": _s(["kg", "kg", "kg"]),
            "detected_prefix": _f([1, 1, 1]),
            "unit_factor_effective": _f([1000, 1000, 1000]),
        }
    )


def test_build_audit_attributes_all_commodity_to_each_applied() -> None:
    audit = build_standardize_layer_audit(_audit_rules(), _matched_counts(), ("rules.xlsx",))
    assert audit.columns == [
        "affected_rows",
        "rule_file_identifier",
        "commodity_key",
        "unit_source",
        "unit_target",
        "unit_factor",
        "unit_offset",
        "source_unit_raw",
        "detected_prefix",
        "unit_factor_effective",
    ]
    assert sorted(audit.get_column("commodity_key").to_list()) == ["corn", "rice", "wheat"]
    assert audit.get_column("affected_rows").to_list() == [1, 1, 1]
    assert audit.get_column("unit_factor_effective").unique().to_list() == [1000.0]


def test_build_audit_empty_rules_returns_empty_schema() -> None:
    audit = build_standardize_layer_audit(pl.DataFrame(), _matched_counts(), ("rules.xlsx",))
    assert audit.height == 0
    assert "unit_factor_effective" in audit.columns


# --------------------------------------------------------------------------- diagnostics


def test_attach_diagnostics_aggregation_fields() -> None:
    diagnostics = attach_standardize_diagnostics(
        pl.DataFrame({"value": _f([1, 2, 3])}),
        clean_rows_count=5,
        matched_count=3,
        unmatched_count=2,
        rules_count=1,
        rule_sources=("rules.xlsx",),
        aggregation_enabled=True,
        rows_before_aggregation=5,
        rows_after_aggregation=3,
    )
    assert diagnostics.aggregation_enabled is True
    assert diagnostics.rows_before_aggregation == 5
    assert diagnostics.rows_after_aggregation == 3
    assert diagnostics.collapsed_rows_count == 2
    assert diagnostics.aggregated_groups_count == 3


def test_attach_diagnostics_no_rules_message() -> None:
    diagnostics = attach_standardize_diagnostics(
        pl.DataFrame({"value": _f([1])}),
        clean_rows_count=1,
        matched_count=0,
        unmatched_count=1,
        rules_count=0,
        rule_sources=("template.xlsx",),
    )
    assert diagnostics.applied_rules == 0
    assert diagnostics.messages == ("no numeric standardization rules found",)
    assert diagnostics.rows_before_aggregation is None


# ----------------------------------------------------------------- readers + orchestration


def test_ensure_template_creates_file(config: Config) -> None:
    template_path = ensure_standardize_template_exists(config)
    assert template_path.is_file()
    assert template_path.parent == config.paths.data.audit.templates_dir


def test_read_workbook_excludes_master_unit(tmp_path: Path) -> None:
    path = tmp_path / "rules.xlsx"
    _write_workbook(
        path,
        {
            "units_standardization": [_RULE_HEADER, ["wheat", "kg", "g", 1000, 0]],
            "master_unit": [_RULE_HEADER, ["wheat", "kg", "g", 999, 0]],
        },
    )
    rules = read_standardize_rule_workbook(path)
    assert rules.height == 1
    assert rules.get_column("unit_factor").to_list() == ["1000"]  # master_unit (999) excluded


def test_read_all_discovers_and_reads(config: Config) -> None:
    standardization = config.paths.data.import_.standardization
    _write_workbook(
        standardization / "standardize_rules.xlsx",
        {"units_standardization": [_RULE_HEADER, ["rice", "tonnes", "kg", 1000, 0]]},
    )
    payload = read_all_standardize_rule_files(config)
    assert payload.rules.height == 1
    assert len(payload.source_paths) == 1


def test_run_end_to_end(config: Config) -> None:
    _write_workbook(
        config.paths.data.import_.standardization / "standardize_rules.xlsx",
        {"units_standardization": [_RULE_HEADER, ["wheat", "kg", "g", 1000, 0]]},
    )
    clean = pl.DataFrame(
        {"commodity": _s(["Wheat", "Rice"]), "unit": _s(["kg", "kg"]), "value": _s(["2", "3"])}
    )
    result = run_standardize_units_layer_batch(clean, config)
    assert result.data.sort("commodity").get_column("value").to_list() == [3.0, 2000.0]
    assert result.diagnostics.matched_count == 1
    assert result.diagnostics.unmatched_count == 1
    assert result.diagnostics.applied_rules == 1
    assert result.audit.height == 1


def test_run_with_no_rule_files(config: Config) -> None:
    config.paths.data.import_.standardization.mkdir(parents=True, exist_ok=True)
    clean = pl.DataFrame({"commodity": _s(["wheat"]), "unit": _s(["kg"]), "value": _s(["2"])})
    result = run_standardize_units_layer_batch(clean, config)
    assert result.diagnostics.applied_rules == 0
    assert result.diagnostics.messages == ("no numeric standardization rules found",)
    assert result.data.get_column("value").to_list() == [2.0]
