"""Tests for the centralized constants."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from whep_digitize.setup.constants import get_pipeline_constants


def test_constants_is_cached_singleton() -> None:
    assert get_pipeline_constants() is get_pipeline_constants()


def test_canonical_row_order() -> None:
    constants = get_pipeline_constants()
    assert constants.sorting.stage_row_order == (
        "hemisphere",
        "continent",
        "polity",
        "commodity",
        "variable",
        "unit",
        "year",
        "value",
        "notes",
        "footnotes",
        "yearbook",
        "document",
    )


def test_pinned_scalar_values() -> None:
    constants = get_pipeline_constants()
    assert constants.dataset_default_name == "whep_data_raw"
    assert constants.na_placeholder == "..NA_INTERNAL.."
    assert constants.na_match_key == "..NA_MATCH_KEY.."
    assert constants.postpro.rule_match_wildcard_token == "#ANY#"
    assert constants.performance.import_workbook_batch_size == 32
    assert constants.performance.import_parallel_workers == "auto"
    assert constants.defaults.notes_value is None
    # Only the import stage checkpoints, under this name.
    assert constants.checkpoints.import_stage_name == "import_pipeline"


def test_audit_numeric_string_pattern() -> None:
    # The stricter-than-parser audit regex: no negatives / scientific / signs.
    assert get_pipeline_constants().patterns.audit_numeric_string == r"^[0-9]+(\.[0-9]+)?$"


def test_canonical_rule_columns() -> None:
    constants = get_pipeline_constants()
    assert constants.postpro.canonical_rule_columns == (
        "column_source",
        "value_source_raw",
        "value_source",
        "column_target",
        "value_target_raw",
        "value_target",
    )


def test_column_groups() -> None:
    columns = get_pipeline_constants().columns
    assert columns.base == ("continent", "polity", "unit", "footnotes")
    assert columns.value == ("year", "value")
    assert "commodity" in columns.id_vars


def test_multi_pass_defaults() -> None:
    multi_pass = get_pipeline_constants().postpro.multi_pass
    assert multi_pass.max_passes_by_stage["clean"] == 10
    assert multi_pass.max_passes_by_stage["harmonize"] == 10
    assert multi_pass.cycle_policy == "warn"


def test_constants_are_immutable() -> None:
    constants: Any = get_pipeline_constants()
    with pytest.raises(dataclasses.FrozenInstanceError):
        constants.dataset_default_name = "mutated"


def test_alias_and_export_config() -> None:
    constants = get_pipeline_constants()
    assert constants.header_normalization.canonical_aliases["country"] == "polity"
    assert constants.export_config.export_layers == ("harmonize",)
    assert constants.export_config.processed_suffix == ".tsv"
