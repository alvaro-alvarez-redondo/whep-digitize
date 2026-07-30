"""Parity test: target-update application must match the R golden byte-for-byte.

Runs ``apply_target_updates_with_strategy`` (port of ``23-target-apply.R``) over four frozen
scenarios and asserts the mutated target column, ``applied`` flag, ``changed_value_count``, and
overwrite-events table all equal R's output:

* **A** — ``last_rule_wins`` fast path (unique rows) with condition match / no-match, a literal
  wildcard on a non-tokenized column, and a transliteration match.
* **B** — ``last_rule_wins`` slow path: order-column stable sort, group-last, overwrite events
  only where candidates differ, a null candidate pasted as ``"NA"``, and a null selected value.
* **C** — ``concatenate`` with a filtered conditioned update.
* **D** — wildcard-already-present removal feeding ``concatenate``.

This guards parity risk #4 (last-rule-wins ordering) and #10 (in-place ``set`` -> functional
scatter). Goldens are committed, so this runs on any checkout — CI included. A missing one still
skips here; ``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from r_harness import FIXTURES_DIR
from registry import CAPTURES

from whep_digitize.postpro.rule_engine.target_apply import (
    TargetApplyResult,
    apply_target_updates_with_strategy,
)

_SPEC = CAPTURES["target_apply"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME

_EVENTS_SCHEMA = {
    "dataset_name": pl.String,
    "execution_stage": pl.String,
    "rule_file_identifier": pl.String,
    "column_source": pl.String,
    "column_target": pl.String,
    "row_id": pl.Int64,
    "candidate_count": pl.Int64,
    "unique_candidate_count": pl.Int64,
    "selected_value": pl.String,
    "candidate_values": pl.String,
}


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with "
            f"`python tests/parity/capture.py {_SPEC.module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _gold_scalar(name: str) -> str:
    value = _gold(name)[0]
    assert value is not None
    return value


def _gold_ints(name: str) -> list[int]:
    return [int(value) for value in _gold(name) if value is not None]


def _string_frame(columns: dict[str, list[str | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in columns.items()}
    )


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, list[str | None]]:
    data: dict[str, list[str | None]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def results(fixture_data: dict[str, list[str | None]]) -> dict[str, TargetApplyResult]:
    fx = fixture_data
    scenario_a = apply_target_updates_with_strategy(
        _string_frame({"unit": fx["dataset_unit"]}),
        _string_frame(
            {
                "row_id": fx["A_row_id"],
                "value_target_result": fx["A_value"],
                "value_target_raw": fx["A_cond"],
            }
        ),
        "unit",
        dataset_name="whep",
        execution_stage="clean",
        rule_file_identifier="rules.xlsx",
        source_column="commodity",
    )
    scenario_b = apply_target_updates_with_strategy(
        _string_frame({"unit": fx["dataset_unit"]}),
        _string_frame(
            {
                "row_id": fx["B_row_id"],
                "value_target_result": fx["B_value"],
                "value_target_raw": fx["B_cond"],
                "seq": fx["B_seq"],
            }
        ),
        "unit",
        order_columns=["seq"],
        dataset_name="whep",
        execution_stage="clean",
        rule_file_identifier="rules.xlsx",
        source_column="commodity",
    )
    scenario_c = apply_target_updates_with_strategy(
        _string_frame({"notes": fx["dataset_notes"]}),
        _string_frame(
            {
                "row_id": fx["C_row_id"],
                "value_target_result": fx["C_value"],
                "value_target_raw": fx["C_cond"],
            }
        ),
        "notes",
        dataset_name="whep",
        execution_stage="clean",
        rule_file_identifier="rules.xlsx",
        source_column="commodity",
    )
    scenario_d = apply_target_updates_with_strategy(
        _string_frame({"notes": fx["dataset_notes_d"]}),
        _string_frame(
            {
                "row_id": fx["D_row_id"],
                "value_target_result": fx["D_value"],
                "value_target_raw": fx["D_cond"],
            }
        ),
        "notes",
        dataset_name="whep",
        execution_stage="harmonize",
        rule_file_identifier="rulesD.xlsx",
        source_column="polity",
    )
    return {"A": scenario_a, "B": scenario_b, "C": scenario_c, "D": scenario_d}


@pytest.mark.parity
def test_scenario_a_fast_path(results: dict[str, TargetApplyResult]) -> None:
    result = results["A"]
    assert result.dataset.get_column("unit").to_list() == _gold("A_unit")
    assert result.applied == (_gold_scalar("A_applied") == "TRUE")
    assert result.changed_value_count == int(_gold_scalar("A_changed"))
    assert result.overwrite_events.height == int(_gold_scalar("A_ev_nrow"))


@pytest.mark.parity
def test_scenario_b_slow_path_and_events(results: dict[str, TargetApplyResult]) -> None:
    result = results["B"]
    assert result.dataset.get_column("unit").to_list() == _gold("B_unit")
    assert result.applied == (_gold_scalar("B_applied") == "TRUE")
    assert result.changed_value_count == int(_gold_scalar("B_changed"))
    assert result.overwrite_events.height == int(_gold_scalar("B_ev_nrow"))

    expected_events = pl.DataFrame(
        {
            "dataset_name": _gold("B_ev_dataset_name"),
            "execution_stage": _gold("B_ev_execution_stage"),
            "rule_file_identifier": _gold("B_ev_rule_file_identifier"),
            "column_source": _gold("B_ev_column_source"),
            "column_target": _gold("B_ev_column_target"),
            "row_id": _gold_ints("B_ev_row_id"),
            "candidate_count": _gold_ints("B_ev_candidate_count"),
            "unique_candidate_count": _gold_ints("B_ev_unique_candidate_count"),
            "selected_value": _gold("B_ev_selected_value"),
            "candidate_values": _gold("B_ev_candidate_values"),
        },
        schema=_EVENTS_SCHEMA,
    )
    assert_frame_equal(result.overwrite_events, expected_events, check_dtypes=True)


@pytest.mark.parity
def test_scenario_c_concatenate(results: dict[str, TargetApplyResult]) -> None:
    result = results["C"]
    assert result.dataset.get_column("notes").to_list() == _gold("C_notes")
    assert result.applied == (_gold_scalar("C_applied") == "TRUE")
    assert result.changed_value_count == int(_gold_scalar("C_changed"))
    assert result.overwrite_events.height == int(_gold_scalar("C_ev_nrow"))


@pytest.mark.parity
def test_scenario_d_wildcard_removal(results: dict[str, TargetApplyResult]) -> None:
    result = results["D"]
    assert result.dataset.get_column("notes").to_list() == _gold("D_notes")
    assert result.applied == (_gold_scalar("D_applied") == "TRUE")
    assert result.changed_value_count == int(_gold_scalar("D_changed"))
    assert result.overwrite_events.height == int(_gold_scalar("D_ev_nrow"))
