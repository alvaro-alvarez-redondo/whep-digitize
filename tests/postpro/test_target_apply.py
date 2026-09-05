"""Unit tests for the postpro rule-engine target-update application.

Covers :mod:`whep_digitize.postpro.rule_engine.target_apply`. Byte
parity is covered in ``tests/parity/test_target_apply_parity.py``; these tests pin the
behavioral contract (concatenate strategy, condition matching, wildcard removal,
functional scatter, validation).

The ``last_rule_wins`` and ``token_substitute`` strategies are now handled by
``conditional_group`` via symmetric token substitution and are tested there.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import pytest
from polars.testing import assert_frame_equal

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


# --------------------------------------------------------------------------- strategy rejection


def test_non_concatenate_column_raises_validation_error() -> None:
    """Columns not configured for 'concatenate' should raise ValidationError.

    Strategies like 'token_substitute' are dispatched by conditional_group and
    should not reach apply_target_updates_with_strategy.
    """
    updates = _updates(row_id=["1"], value_target_result=["X"], value_target_raw=[None])
    with pytest.raises(ValidationError, match="concatenate"):
        _apply(_ds("unit", ["kg"]), updates, "unit")


# --------------------------------------------------------------------------- concatenate


def test_concatenate_merges_existing_first_dedupe() -> None:
    updates = _updates(
        row_id=["1", "1"], value_target_result=["b; c", "d"], value_target_raw=[None, None]
    )
    result = _apply(_ds("notes", ["a; b"]), updates, "notes")
    assert result.dataset.get_column("notes").to_list() == ["a; b; c; d"]


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
    updates = _updates(row_id=["1"], value_target_result=["a"], value_target_raw=["#ANY#"])
    result = _apply(_ds("notes", ["a; b"]), updates, "notes")
    # candidate "a" already a token of "a; b" -> removed -> nothing applied.
    assert result.applied is False
    assert result.dataset.get_column("notes").to_list() == ["a; b"]


def test_wildcard_kept_when_value_absent() -> None:
    updates = _updates(row_id=["1"], value_target_result=["z"], value_target_raw=["#ANY#"])
    result = _apply(_ds("notes", ["a; b"]), updates, "notes")
    assert result.dataset.get_column("notes").to_list() == ["a; b; z"]


# --------------------------------------------------------------------------- no in-place mutation


def test_dataset_is_not_mutated_in_place() -> None:
    dataset = _ds("notes", ["a", "b"])
    before = dataset.clone()
    _apply(
        dataset,
        _updates(row_id=["1"], value_target_result=["X"], value_target_raw=[None]),
        "notes",
    )
    assert_frame_equal(dataset, before)


# --------------------------------------------------------------------------- row-id + validation


def test_unparseable_row_id_is_dropped() -> None:
    updates = _updates(
        row_id=["abc", "1"], value_target_result=["x", "y"], value_target_raw=[None, None]
    )
    result = _apply(_ds("notes", ["a"]), updates, "notes")
    # "abc" row id dropped; "y" concatenated into existing "a" -> "a; y".
    assert result.dataset.get_column("notes").to_list() == ["a; y"]


def test_empty_updates_returns_not_applied() -> None:
    empty = pl.DataFrame(
        schema={
            "row_id": pl.String,
            "value_target_result": pl.String,
            "value_target_raw": pl.String,
        }
    )
    result = _apply(_ds("notes", ["a"]), empty, "notes")
    assert result.applied is False
    assert result.changed_value_count == 0
    assert result.dataset.get_column("notes").to_list() == ["a"]


def test_missing_target_column_raises() -> None:
    updates = _updates(row_id=["1"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(_ds("other", ["a"]), updates, "notes")


def test_missing_required_update_column_raises() -> None:
    updates = pl.DataFrame({"row_id": pl.Series("row_id", ["1"], dtype=pl.String)})
    with pytest.raises(ValidationError):
        _apply(_ds("notes", ["a"]), updates, "notes")


def test_out_of_bounds_row_id_raises() -> None:
    updates = _updates(row_id=["5"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(_ds("notes", ["a"]), updates, "notes")


def test_empty_string_argument_raises() -> None:
    updates = _updates(row_id=["1"], value_target_result=["x"], value_target_raw=[None])
    with pytest.raises(ValidationError):
        _apply(_ds("notes", ["a"]), updates, "")
