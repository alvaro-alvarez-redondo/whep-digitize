"""Parity test: standardize aggregation + layer audit must match the R golden.

Exercises the port of ``24-standardize-aggregation.R`` (``aggregate_standardized_rows``) and the
audit merge from ``24-standardize-orchestration.R`` (``build_standardize_layer_audit``). Asserts
the aggregated measure (all-NA group → null; unique rows kept) and the audit's
commodity/affected/effective/target — the ``all commodity`` rule attributed to each applied
commodity. If a golden is absent, the test skips.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.standardize_units.aggregation import aggregate_standardized_rows
from whep_digitize.postpro.standardize_units.orchestration import build_standardize_layer_audit
from whep_digitize.postpro.standardize_units.rules_setup import prepare_standardize_rules

_SPEC = GOLDENS["standardize_agg"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME


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
def fixture_data() -> dict[str, list[str | None]]:
    data: dict[str, list[str | None]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def _string(values: list[str | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


@pytest.mark.parity
def test_aggregate_matches_golden(fixture_data: dict[str, list[str | None]]) -> None:
    agg_in = pl.DataFrame(
        {
            "commodity": _string(fixture_data["agg_commodity"]),
            "unit": _string(fixture_data["agg_unit"]),
            "value": pl.Series("value", _floats(fixture_data["agg_value"]), dtype=pl.Float64),
        }
    )
    aggregated = aggregate_standardized_rows(agg_in, "value").sort(["commodity", "unit"])
    assert aggregated.get_column("commodity").to_list() == _gold("agg_commodity")
    assert aggregated.get_column("value").to_list() == pytest.approx(
        _floats(_gold("agg_value")), nan_ok=True
    )
    assert [str(aggregated.height)] == _gold("agg_nrow")


@pytest.mark.parity
def test_layer_audit_matches_golden(fixture_data: dict[str, list[str | None]]) -> None:
    layer_rules = prepare_standardize_rules(
        pl.DataFrame(
            {
                "commodity_key": _string(fixture_data["r_commodity"]),
                "unit_source": _string(fixture_data["r_source"]),
                "unit_target": _string(fixture_data["r_target"]),
                "unit_factor": pl.Series(
                    "unit_factor", _floats(fixture_data["r_factor"]), dtype=pl.Float64
                ),
                "unit_offset": pl.Series(
                    "unit_offset", _floats(fixture_data["r_offset"]), dtype=pl.Float64
                ),
                "source_rule_sheet": _string(fixture_data["r_sheet"]),
                "source_rule_file": _string(fixture_data["r_file"]),
            }
        )
    )
    matched_rule_counts = pl.DataFrame(
        {
            "rule_commodity_match_key": _string(fixture_data["m_rule"]),
            "applied_commodity_match_key": _string(fixture_data["m_applied"]),
            "unit_source_key": _string(fixture_data["m_unitkey"]),
            "affected_rows": pl.Series(
                "affected_rows",
                [int(v) for v in fixture_data["m_affected"] if v is not None],
                dtype=pl.Int64,
            ),
            "source_unit_raw": _string(fixture_data["m_raw"]),
            "detected_prefix": pl.Series(
                "detected_prefix", _floats(fixture_data["m_prefix"]), dtype=pl.Float64
            ),
            "unit_factor_effective": pl.Series(
                "unit_factor_effective", _floats(fixture_data["m_eff"]), dtype=pl.Float64
            ),
        }
    )
    source_file = fixture_data["r_file"][0]
    assert source_file is not None
    audit = build_standardize_layer_audit(layer_rules, matched_rule_counts, (source_file,)).sort(
        "commodity_key"
    )
    assert audit.get_column("commodity_key").to_list() == _gold("audit_commodity")
    assert [str(count) for count in audit.get_column("affected_rows").to_list()] == _gold(
        "audit_affected"
    )
    assert audit.get_column("unit_target").to_list() == _gold("audit_target")
    assert audit.get_column("unit_factor_effective").to_list() == pytest.approx(
        _floats(_gold("audit_effective"))
    )
    assert [str(audit.height)] == _gold("audit_nrow")
