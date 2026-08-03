"""Parity test: postpro diagnostics summary tables must match the R golden.

Exercises the port of ``25-rule-summaries.R`` + ``25-standardize-summaries.R``:
``summarize_stage_rules`` (value filled from ``*_result``), ``build_unmatched_rule_summary``
(anti-join with NA-matching), ``summarize_standardize_rules``, and
``build_unmatched_standardize_rule_summary`` via the normalized-key counts branch. If a golden is
absent, the test skips.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.diagnostics.rule_summaries import (
    build_unmatched_rule_summary,
    summarize_stage_rules,
)
from whep_digitize.postpro.diagnostics.standardize_summaries import (
    build_unmatched_standardize_rule_summary,
    summarize_standardize_rules,
)

_SPEC = GOLDENS["diagnostics"]
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


@pytest.fixture(scope="module")
def data() -> dict[str, list[str]]:
    payload: dict[str, list[str]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload


def _s(values: list[str]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


def _i(values: list[str]) -> pl.Series:
    return pl.Series([int(v) for v in values], dtype=pl.Int64)


def _f(values: list[str]) -> pl.Series:
    return pl.Series([float(v) for v in values], dtype=pl.Float64)


@pytest.mark.parity
def test_clean_summaries_match_golden(data: dict[str, list[str]]) -> None:
    clean_audit = pl.DataFrame(
        {
            "loop": _i(data["ca_loop"]),
            "rule_file_identifier": _s(data["ca_rf"]),
            "column_source": _s(data["ca_cs"]),
            "value_source_raw": _s(data["ca_vsr"]),
            "value_source_result": _s(data["ca_vsres"]),
            "column_target": _s(data["ca_ct"]),
            "value_target_raw": _s(data["ca_vtr"]),
            "value_target_result": _s(data["ca_vtres"]),
            "affected_rows": _i(data["ca_aff"]),
        }
    )
    summary = summarize_stage_rules(clean_audit)
    assert [str(v) for v in summary.get_column("loop").to_list()] == _gold("cs_loop")
    assert summary.get_column("value_source").to_list() == _gold("cs_value_source")
    assert summary.get_column("value_target").to_list() == _gold("cs_value_target")
    assert summary.get_column("column_target").to_list() == _gold("cs_column_target")

    catalog = pl.DataFrame(
        {
            "rule_file_identifier": _s(data["cc_rf"]),
            "column_source": _s(data["cc_cs"]),
            "value_source_raw": _s(data["cc_vsr"]),
            "value_source": _s(data["cc_vs"]),
            "column_target": _s(data["cc_ct"]),
            "value_target_raw": _s(data["cc_vtr"]),
            "value_target": _s(data["cc_vt"]),
        }
    )
    unmatched = build_unmatched_rule_summary(catalog, summary)
    assert [str(unmatched.height)] == _gold("cu_nrow")
    assert unmatched.get_column("column_source").to_list() == _gold("cu_column_source")
    assert unmatched.get_column("value_source_raw").to_list() == _gold("cu_value_source_raw")
    assert [str(v) for v in unmatched.get_column("affected_rows").to_list()] == _gold("cu_affected")


@pytest.mark.parity
def test_standardize_summaries_match_golden(data: dict[str, list[str]]) -> None:
    std_audit = pl.DataFrame(
        {
            "rule_file_identifier": _s(data["sa_rf"]),
            "commodity_key": _s(data["sa_commodity"]),
            "unit_source": _s(data["sa_source"]),
            "unit_target": _s(data["sa_target"]),
            "unit_factor": _f(data["sa_factor"]),
            "unit_offset": _f(data["sa_offset"]),
            "affected_rows": _i(data["sa_aff"]),
        }
    )
    summary = summarize_standardize_rules(std_audit)
    assert summary.get_column("commodity_key").to_list() == _gold("ss_commodity")
    assert summary.get_column("unit_target").to_list() == _gold("ss_unit_target")
    assert [str(v) for v in summary.get_column("affected_rows").to_list()] == _gold("ss_affected")

    catalog = pl.DataFrame(
        {
            "rule_file_identifier": _s(data["sc_rf"]),
            "commodity_key": _s(data["sc_commodity"]),
            "unit_source": _s(data["sc_source"]),
            "unit_target": _s(data["sc_target"]),
            "unit_factor": _f(data["sc_factor"]),
            "unit_offset": _f(data["sc_offset"]),
        }
    )
    counts = pl.DataFrame(
        {"rule_commodity_match_key": _s(data["sm_rule"]), "unit_source_key": _s(data["sm_unitkey"])}
    )
    unmatched = build_unmatched_standardize_rule_summary(catalog, summary, counts)
    assert [str(unmatched.height)] == _gold("su_nrow")
    assert unmatched.get_column("commodity_key").to_list() == _gold("su_commodity")
    assert unmatched.get_column("unit_source").to_list() == _gold("su_unit_source")
    assert [str(v) for v in unmatched.get_column("affected_rows").to_list()] == _gold("su_affected")
