"""Unit tests for the postpro rule-engine conditional rule-group application.

Port of ``23-conditional-group.R`` (:mod:`whep_digitize.postpro.rule_engine.conditional_group`).
Byte parity vs R is covered in ``tests/parity/test_conditional_group_parity.py``; these tests pin
the behavioral contract (source/target scatter, independent changed_columns, audit table,
overwrite events, argument validation) without needing R.
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.rule_engine.conditional_group import (
    ConditionalGroupResult,
    PreparedConditionalGroup,
    apply_conditional_rule_group,
    prepare_conditional_rule_group,
)
from whep_digitize.setup.errors import ValidationError

_RULE_COLUMNS = (
    "column_source",
    "value_source_raw",
    "value_source",
    "column_target",
    "value_target_raw",
    "value_target",
)


def _group(
    rows: list[tuple[str | None, ...]], *, present: list[bool] | None = None
) -> pl.DataFrame:
    frame = pl.DataFrame(
        {
            name: pl.Series(name, [row[i] for row in rows], dtype=pl.String)
            for i, name in enumerate(_RULE_COLUMNS)
        }
    )
    flags = present if present is not None else [row[2] is not None for row in rows]
    return frame.with_columns(pl.Series("source_value_column_present", flags, dtype=pl.Boolean))


def _dataset(**columns: list[str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in columns.items()}
    )


def _apply(
    dataset: pl.DataFrame,
    *,
    group_rules: pl.DataFrame | None = None,
    prepared_group: PreparedConditionalGroup | None = None,
    dataset_name: str = "whep",
) -> ConditionalGroupResult:
    """Call the port with fixed labels (the arguments under test vary per test)."""
    return apply_conditional_rule_group(
        dataset,
        group_rules=group_rules,
        prepared_group=prepared_group,
        stage_name="clean",
        dataset_name=dataset_name,
        rule_file_id="rules.xlsx",
        execution_timestamp_utc="2026-01-01T00:00:00Z",
    )


def test_source_and_target_both_change() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["RICE"]
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.changed_value_count == 2
    assert result.changed_columns == ("commodity", "unit")


def test_source_only_rewrite_does_not_mark_target() -> None:
    # value_target equals the current unit -> the target update is a no-op; only the source changes.
    dataset = _dataset(commodity=["wheat"], unit=["kg"])
    group = _group([("commodity", "wheat", "WHEAT", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["WHEAT"]
    assert result.data.get_column("unit").to_list() == ["kg"]
    assert result.changed_value_count == 1
    assert result.changed_columns == ("commodity",)


def test_target_only_when_source_value_absent() -> None:
    dataset = _dataset(commodity=["maize"], unit=["kg"])
    group = _group([("commodity", "maize", None, "unit", "kg", "tonne")], present=[False])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["maize"]
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.changed_columns == ("unit",)


def test_no_match_changes_nothing() -> None:
    dataset = _dataset(commodity=["barley"], unit=["kg"])
    group = _group([("commodity", "wheat", "WHEAT", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["barley"]
    assert result.changed_value_count == 0
    assert result.changed_columns == ()
    assert result.audit.height == 0


def test_target_condition_must_match_current_value() -> None:
    # The rule's target condition ("kg") does not match the current unit ("g") -> no application.
    dataset = _dataset(commodity=["rice"], unit=["g"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.changed_value_count == 0
    assert result.data.get_column("commodity").to_list() == ["rice"]


def test_transliteration_source_match() -> None:
    dataset = _dataset(commodity=["Café"], unit=["kg"])
    group = _group([("commodity", "cafe", "COFFEE", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["COFFEE"]
    assert result.data.get_column("unit").to_list() == ["tonne"]


def test_audit_groups_and_counts_affected_rows() -> None:
    dataset = _dataset(commodity=["wheat", "wheat", "rye"], unit=["kg", "kg", "kg"])
    group = _group(
        [
            ("commodity", "wheat", "WHEAT", "unit", "kg", "tonne"),
            ("commodity", "rye", "RYE", "unit", "kg", "gram"),
        ]
    )
    result = _apply(dataset, group_rules=group)
    audit = result.audit
    assert audit.height == 2
    # Ordered by value_source_raw: "rye" before "wheat".
    assert audit.get_column("value_source_raw").to_list() == ["rye", "wheat"]
    assert audit.get_column("affected_rows").to_list() == [1, 2]
    assert audit.get_column("dataset_name").to_list() == ["whep", "whep"]
    assert audit.get_column("execution_stage").to_list() == ["clean", "clean"]


def test_concatenate_target_column() -> None:
    dataset = _dataset(commodity=["rice"], notes=["a; b"])
    group = _group([("commodity", "rice", None, "notes", "__ANY__", "b; c")], present=[False])
    result = _apply(dataset, group_rules=group)
    # notes uses the concatenate strategy: existing "a; b" merged with "b; c" -> "a; b; c".
    assert result.data.get_column("notes").to_list() == ["a; b; c"]
    assert result.changed_columns == ("notes",)


def test_conflicting_target_rules_emit_overwrite_event() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group(
        [
            ("commodity", "rice", None, "unit", "kg", "tonne"),
            ("commodity", "rice", None, "unit", "kg", "gram"),
        ],
        present=[False, False],
    )
    result = _apply(dataset, group_rules=group)
    # Two rules hit the same row with different target values -> last-rule-wins overwrite event.
    assert result.overwrite_events.height == 1
    assert result.data.get_column("unit").to_list() == ["gram"]


def test_prepared_group_path() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    prepared = prepare_conditional_rule_group(
        _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")]), "clean"
    )
    result = _apply(dataset, prepared_group=prepared)
    assert result.data.get_column("commodity").to_list() == ["RICE"]


def test_requires_exactly_one_of_group_or_prepared() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    prepared = prepare_conditional_rule_group(group, "clean")
    with pytest.raises(ValidationError):
        _apply(dataset)
    with pytest.raises(ValidationError):
        _apply(dataset, group_rules=group, prepared_group=prepared)


def test_empty_string_argument_raises() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    with pytest.raises(ValidationError):
        _apply(dataset, group_rules=group, dataset_name="")


def test_prepare_rejects_empty_group() -> None:
    empty = _group([]).clear()
    with pytest.raises(ValidationError):
        prepare_conditional_rule_group(empty, "clean")
