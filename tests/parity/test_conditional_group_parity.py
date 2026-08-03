"""Parity test: conditional rule-group application must match the R golden byte-for-byte.

Runs ``apply_conditional_rule_group`` (port of ``23-conditional-group.R``) over four scenarios and
asserts the mutated source/target columns, ``changed_value_count``, ``changed_columns``, and the
audit table all equal R's output:

* **M** — two rules over four rows incl. a transliteration match (``"Café"`` via ``"cafe"``):
  audit grouping + affected-row counts + both columns changing.
* **SO** — a source rewrite whose target update is a no-op: must mark **only** the source column.
* **TO** — no source-result value: target-only.
* **NM** — no match: nothing changes, empty audit.

Guards the cartesian-join ordering (parity risk #4/#7) and the in-place ``set`` -> functional
scatter (#10). Goldens are committed, so this runs on any checkout — CI included. A missing one
still skips here; ``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_frame_equal

from whep_digitize.postpro.rule_engine.conditional_group import (
    ConditionalGroupResult,
    apply_conditional_rule_group,
)

_SPEC = GOLDENS["conditional_group"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_BOOL = {"TRUE": True, "FALSE": False}

_AUDIT_SCHEMA = {
    "dataset_name": pl.String,
    "column_source": pl.String,
    "value_source_raw": pl.String,
    "value_source_result": pl.String,
    "column_target": pl.String,
    "value_target_raw": pl.String,
    "value_target_result": pl.String,
    "affected_rows": pl.Int64,
    "execution_timestamp_utc": pl.String,
    "rule_file_identifier": pl.String,
    "execution_stage": pl.String,
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


def _series(values: list[str | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, list[str | None]]:
    data: dict[str, list[str | None]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def _group(fixture_data: dict[str, list[str | None]], prefix: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "column_source": _series(fixture_data[f"{prefix}_cs"]),
            "value_source_raw": _series(fixture_data[f"{prefix}_vsr"]),
            "value_source": _series(fixture_data[f"{prefix}_vs"]),
            "column_target": _series(fixture_data[f"{prefix}_ct"]),
            "value_target_raw": _series(fixture_data[f"{prefix}_vtr"]),
            "value_target": _series(fixture_data[f"{prefix}_vt"]),
            "source_value_column_present": pl.Series(
                [_BOOL[flag] for flag in fixture_data[f"{prefix}_svc"] if flag is not None],
                dtype=pl.Boolean,
            ),
        }
    )


def _dataset(fixture_data: dict[str, list[str | None]], prefix: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "commodity": _series(fixture_data[f"{prefix}_ds_commodity"]),
            "unit": _series(fixture_data[f"{prefix}_ds_unit"]),
        }
    )


@pytest.fixture(scope="module")
def results(fixture_data: dict[str, list[str | None]]) -> dict[str, ConditionalGroupResult]:
    return {
        scenario: apply_conditional_rule_group(
            _dataset(fixture_data, scenario),
            group_rules=_group(fixture_data, f"{scenario}_r"),
            stage_name="clean",
            dataset_name="whep",
            rule_file_id="rules.xlsx",
            execution_timestamp_utc="2026-01-01T00:00:00Z",
        )
        for scenario in ("M", "SO", "TO", "NM")
    }


@pytest.mark.parity
@pytest.mark.parametrize("scenario", ["M", "SO", "TO", "NM"])
def test_scenario_outputs(results: dict[str, ConditionalGroupResult], scenario: str) -> None:
    result = results[scenario]
    assert result.data.get_column("commodity").to_list() == _gold(f"{scenario}_commodity")
    assert result.data.get_column("unit").to_list() == _gold(f"{scenario}_unit")
    assert result.changed_value_count == int(_gold_scalar(f"{scenario}_changed"))
    assert list(result.changed_columns) == _gold(f"{scenario}_changed_columns")
    assert result.audit.height == int(_gold_scalar(f"{scenario}_audit_nrow"))


@pytest.mark.parity
def test_multi_audit_table(results: dict[str, ConditionalGroupResult]) -> None:
    expected = pl.DataFrame(
        {
            "dataset_name": _gold("M_audit_dataset_name"),
            "column_source": _gold("M_audit_column_source"),
            "value_source_raw": _gold("M_audit_value_source_raw"),
            "value_source_result": _gold("M_audit_value_source_result"),
            "column_target": _gold("M_audit_column_target"),
            "value_target_raw": _gold("M_audit_value_target_raw"),
            "value_target_result": _gold("M_audit_value_target_result"),
            "affected_rows": [int(value) for value in _gold("M_audit_affected_rows") if value],
            "execution_timestamp_utc": _gold("M_audit_execution_timestamp_utc"),
            "rule_file_identifier": _gold("M_audit_rule_file_identifier"),
            "execution_stage": _gold("M_audit_execution_stage"),
        },
        schema=_AUDIT_SCHEMA,
    )
    assert_frame_equal(results["M"].audit, expected, check_dtypes=True)
