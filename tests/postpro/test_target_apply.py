"""Unit tests for the postpro rule-engine target-update application.

Covers :mod:`whep_digitize.postpro.rule_engine.target_apply`. Byte
parity is covered in ``tests/parity/test_target_apply_parity.py``; these tests pin the
behavioral contract (strategy dispatch, condition matching, wildcard removal, overwrite-event
emission, functional scatter, validation).
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from whep_digitize.postpro.rule_engine.matching_strategy import (
    empty_last_rule_wins_overwrite_events_df,
)
from whep_digitize.postpro.rule_engine.target_apply import (
    TargetApplyResult,
    apply_target_updates_with_strategy,
)
from whep_digitize.setup.errors import ValidationError


def _apply(
    dataset: pl.DataFrame,
    updates: pl.DataFrame,
    target_column: str,
    *,
    order_columns: Sequence[str] = (),
    apply_condition_match: bool = True,
) -> TargetApplyResult:
    """Call the port with fixed diagnostic labels (the arguments under test vary per test)."""
    return apply_target_updates_with_strategy(
        dataset,
        updates,
        target_column,
        order_columns=order_columns,
        apply_condition_match=apply_condition_match,
        dataset_name="whep",
        execution_stage="clean",
        rule_file_identifier="rules.xlsx",
        source_column="commodity",
    )


def _updates(**columns: list[str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in columns.items()}
    )


def _ds(column: str, values: list[str | None]) -> pl.DataFrame:
    return pl.DataFrame({column: pl.Series(column, values, dtype=pl.String)})


# --------------------------------------------------------------------------- last_rule_wins


def test_fast_path_applies_unique_updates() -> None:
    updates = _updates(
        row_id=["1", "3"], value_target_result=["X", "Z"], value_target_raw=[None, None]
    )
    result = _apply(_ds("unit", ["a", "b", "c"]), updates, "unit")
    assert result.applied is True
    assert result.dataset.get_column("unit").to_list() == ["X", "b", "Z"]
    assert result.changed_value_count == 2
    assert result.overwrite_events.height == 0


def test_condition_match_filters_unmatched() -> None:
    updates = _updates(
        row_id=["1", "2"],
        value_target_result=["X", "Y"],
        value_target_raw=["a", "nomatch"],
    )
    result = _apply(_ds("unit", ["a", "b"]), updates, "unit")
    # row 1 condition "a" matches current "a" -> applied; row 2 "nomatch" != "b" -> dropped.
    assert result.dataset.get_column("unit").to_list() == ["X", "b"]
    assert result.changed_value_count == 1


def test_all_conditions_unmatched_is_not_applied() -> None:
    updates = _updates(row_id=["1"], value_target_result=["Z"], value_target_raw=["nomatch"])
    result = _apply(_ds("unit", ["a"]), updates, "unit")
    assert result.applied is False
    assert result.dataset.get_column("unit").to_list() == ["a"]
    assert result.changed_value_count == 0


def test_apply_condition_match_false_ignores_condition() -> None:
    updates = _updates(row_id=["1"], value_target_result=["Z"], value_target_raw=["nomatch"])
    result = _apply(_ds("unit", ["a"]), updates, "unit", apply_condition_match=False)
    assert result.applied is True
    assert result.dataset.get_column("unit").to_list() == ["Z"]


def test_slow_path_last_candidate_wins_by_order_columns() -> None:
    updates = _updates(
        row_id=["1", "1"],
        value_target_result=["X", "Y"],
        value_target_raw=[None, None],
        seq=["2", "1"],
    )
    result = _apply(_ds("unit", ["a"]), updates, "unit", order_columns=["seq"])
    # sorted by seq: Y(1) then X(2) -> last is X.
    assert result.dataset.get_column("unit").to_list() == ["X"]


def test_slow_path_emits_overwrite_event_on_conflict() -> None:
    updates = _updates(
        row_id=["1", "1"],
        value_target_result=["X", "Y"],
        value_target_raw=[None, None],
        seq=["1", "2"],
    )
    result = _apply(_ds("unit", ["a"]), updates, "unit", order_columns=["seq"])
    assert result.dataset.get_column("unit").to_list() == ["Y"]
    events = result.overwrite_events
    assert events.height == 1
    row = events.row(0, named=True)
    assert row["row_id"] == 1
    assert row["candidate_count"] == 2
    assert row["unique_candidate_count"] == 2
    assert row["selected_value"] == "Y"
    assert row["candidate_values"] == "X; Y"
    assert row["column_source"] == "commodity"
    assert row["column_target"] == "unit"


def test_slow_path_identical_candidates_emit_no_event() -> None:
    updates = _updates(
        row_id=["1", "1"], value_target_result=["X", "X"], value_target_raw=[None, None]
    )
    result = _apply(_ds("unit", ["a"]), updates, "unit")
    assert result.applied is True
    assert result.dataset.get_column("unit").to_list() == ["X"]
    # unique_candidate_count == 1 -> no overwrite event.
    assert result.overwrite_events.height == 0


def test_overwrite_events_schema_matches_empty_events() -> None:
    updates = _updates(
        row_id=["1", "1"], value_target_result=["X", "Y"], value_target_raw=[None, None]
    )
    result = _apply(_ds("unit", ["a"]), updates, "unit")
    assert result.overwrite_events.schema == empty_last_rule_wins_overwrite_events_df().schema


# --------------------------------------------------------------------------- concatenate


def test_concatenate_merges_existing_first_dedupe() -> None:
    updates = _updates(
        row_id=["1", "1"], value_target_result=["b; c", "d"], value_target_raw=[None, None]
    )
    result = _apply(_ds("notes", ["a; b"]), updates, "notes")
    assert result.dataset.get_column("notes").to_list() == ["a; b; c; d"]
    assert result.overwrite_events.height == 0


def test_concatenate_drops_blank_updates() -> None:
    updates = _updates(row_id=["1"], value_target_result=["  "], value_target_raw=[None])
    result = _apply(_ds("notes", ["keep"]), updates, "notes")
    assert result.applied is False
    assert result.dataset.get_column("notes").to_list() == ["keep"]


def test_concatenate_requires_string_target() -> None:
    dataset = pl.DataFrame({"notes": pl.Series("notes", [1, 2], dtype=pl.Int64)})
    updates = _updates(row_id=["1"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(dataset, updates, "notes")


# --------------------------------------------------------------------------- wildcard removal


def test_wildcard_removed_when_value_already_present() -> None:
    updates = _updates(row_id=["1"], value_target_result=["a"], value_target_raw=["__ANY__"])
    result = _apply(_ds("notes", ["a; b"]), updates, "notes")
    # candidate "a" already a token of "a; b" -> removed -> nothing applied.
    assert result.applied is False
    assert result.dataset.get_column("notes").to_list() == ["a; b"]


def test_wildcard_kept_when_value_absent() -> None:
    updates = _updates(row_id=["1"], value_target_result=["z"], value_target_raw=["__ANY__"])
    result = _apply(_ds("notes", ["a; b"]), updates, "notes")
    assert result.dataset.get_column("notes").to_list() == ["a; b; z"]


# --------------------------------------------------------------------------- no in-place mutation


def test_dataset_is_not_mutated_in_place() -> None:
    dataset = _ds("unit", ["a", "b"])
    before = dataset.clone()
    _apply(
        dataset,
        _updates(row_id=["1"], value_target_result=["X"], value_target_raw=[None]),
        "unit",
    )
    assert_frame_equal(dataset, before)


# --------------------------------------------------------------------------- row-id + validation


def test_unparseable_row_id_is_dropped() -> None:
    updates = _updates(
        row_id=["abc", "1"], value_target_result=["x", "y"], value_target_raw=[None, None]
    )
    result = _apply(_ds("unit", ["a"]), updates, "unit")
    assert result.dataset.get_column("unit").to_list() == ["y"]


def test_empty_updates_returns_not_applied() -> None:
    empty = pl.DataFrame(
        schema={
            "row_id": pl.String,
            "value_target_result": pl.String,
            "value_target_raw": pl.String,
        }
    )
    result = _apply(_ds("unit", ["a"]), empty, "unit")
    assert result.applied is False
    assert result.changed_value_count == 0
    assert result.dataset.get_column("unit").to_list() == ["a"]


def test_missing_target_column_raises() -> None:
    updates = _updates(row_id=["1"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(_ds("other", ["a"]), updates, "unit")


def test_missing_required_update_column_raises() -> None:
    updates = pl.DataFrame({"row_id": pl.Series("row_id", ["1"], dtype=pl.String)})
    with pytest.raises(ValidationError):
        _apply(_ds("unit", ["a"]), updates, "unit")


def test_out_of_bounds_row_id_raises() -> None:
    updates = _updates(row_id=["5"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(_ds("unit", ["a"]), updates, "unit")


def test_empty_string_argument_raises() -> None:
    updates = _updates(row_id=["1"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(_ds("unit", ["a"]), updates, "")
