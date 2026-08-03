"""Parity test: unit standardization must match the R golden.

Exercises the port of ``24-rules-setup.R`` (``prepare_standardize_rules``) +
``24-standardize-engine.R`` (``apply_standardize_rules``) over one rich fixture: a specific
prefixed rule (revert), a ``kg`` fallback, a celsius→fahrenheit offset, a comma-thousands prefix
fold, and an unmatched row (parity risk #9). Asserts the converted value + unit, matched/unmatched
counts, and the sorted ``matched_rule_counts`` match R. If a golden is absent, the test skips.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.standardize_units.engine import (
    StandardizeResult,
    apply_standardize_rules,
)
from whep_digitize.postpro.standardize_units.rules_setup import prepare_standardize_rules

_SPEC = GOLDENS["standardize"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_MRC_SORT = ["rule_commodity_match_key", "applied_commodity_match_key", "unit_source_key"]


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with "
            f"`python tests/parity/capture.py {_SPEC.module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _floats(values: list[str | None]) -> list[float | None]:
    return [None if value is None else float(value) for value in values]


@pytest.fixture(scope="module")
def result() -> StandardizeResult:
    data: dict[str, list[str]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    mapped = pl.DataFrame(
        {
            "commodity": pl.Series("commodity", data["commodity"], dtype=pl.String),
            "unit": pl.Series("unit", data["unit"], dtype=pl.String),
            "value": pl.Series("value", data["value"], dtype=pl.String),
        }
    )
    raw_rules = pl.DataFrame(
        {
            "commodity_key": pl.Series("commodity_key", data["rule_commodity"], dtype=pl.String),
            "unit_source": pl.Series("unit_source", data["rule_source"], dtype=pl.String),
            "unit_target": pl.Series("unit_target", data["rule_target"], dtype=pl.String),
            "unit_factor": pl.Series("unit_factor", data["rule_factor"], dtype=pl.String),
            "unit_offset": pl.Series("unit_offset", data["rule_offset"], dtype=pl.String),
        }
    )
    prepared = prepare_standardize_rules(raw_rules)
    return apply_standardize_rules(mapped, prepared, "unit", "value", "commodity")


@pytest.mark.parity
def test_standardize_data_matches_golden(result: StandardizeResult) -> None:
    data = result.data
    assert data.get_column("value").to_list() == pytest.approx(_floats(_gold("value")))
    assert data.get_column("unit").to_list() == _gold("unit")
    assert data.get_column("commodity").to_list() == _gold("commodity")
    assert [str(result.matched_count)] == _gold("matched")
    assert [str(result.unmatched_count)] == _gold("unmatched")


@pytest.mark.parity
def test_standardize_matched_rule_counts_match_golden(result: StandardizeResult) -> None:
    mrc = result.matched_rule_counts.sort(_MRC_SORT)
    assert [str(mrc.height)] == _gold("mrc_nrow")
    assert mrc.get_column("applied_commodity_match_key").to_list() == _gold("mrc_applied")
    assert [str(count) for count in mrc.get_column("affected_rows").to_list()] == _gold(
        "mrc_affected"
    )
    assert mrc.get_column("unit_factor_effective").to_list() == pytest.approx(
        _floats(_gold("mrc_effective"))
    )
