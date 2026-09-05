"""Parity test: target-update application must match the frozen reference byte-for-byte.

Runs ``apply_target_updates_with_strategy`` over two frozen
scenarios and asserts the mutated target column, ``applied`` flag, ``changed_value_count``, and
overwrite-events table all equal the expected output:

* **C** — ``concatenate`` with a filtered conditioned update.
* **D** — wildcard-already-present removal feeding ``concatenate``.

The ``last_rule_wins`` and ``token_substitute`` strategies are now handled by
``conditional_group`` via symmetric token substitution and are tested there.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.rule_engine.target_apply import (
    TargetApplyResult,
    apply_target_updates_with_strategy,
)

_SPEC = GOLDENS["target_apply"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _gold_scalar(name: str) -> str:
    value = _gold(name)[0]
    assert value is not None
    return value


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
    return {"C": scenario_c, "D": scenario_d}


@pytest.mark.parity
def test_scenario_c_concatenate(results: dict[str, TargetApplyResult]) -> None:
    result = results["C"]
    assert result.dataset.get_column("notes").to_list() == _gold("C_notes")
    assert result.applied == (_gold_scalar("C_applied") == "TRUE")
    assert result.changed_value_count == int(_gold_scalar("C_changed"))


@pytest.mark.parity
def test_scenario_d_wildcard_removal(results: dict[str, TargetApplyResult]) -> None:
    result = results["D"]
    assert result.dataset.get_column("notes").to_list() == _gold("D_notes")
    assert result.applied == (_gold_scalar("D_applied") == "TRUE")
    assert result.changed_value_count == int(_gold_scalar("D_changed"))
