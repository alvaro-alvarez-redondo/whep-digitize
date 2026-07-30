"""Parity test: footnote-rule application must match the R golden byte-for-byte.

Runs ``apply_footnote_rules`` (port of ``23-footnote-rules.R``) over one rich dataset + rule set
covering replace / remove / multi-token / precedence (remove>replace, first-replacement) /
NA / empty / trailing-``;`` / whitespace / conditional-target / transliteration / no-op, and
asserts the reconstructed footnotes, the mutated target column, the change count, the changed
columns, and the full audit table all equal R's output.

Guards the ``;``-explode semantics, the cartesian match/resolve/reconstruct, and the
before-image footnote change count. Goldens are committed, so this runs on any checkout — CI
included. A missing one still skips here; ``test_goldens_present.py`` is what makes that a hard
failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from r_harness import FIXTURES_DIR
from registry import CAPTURES

from whep_digitize.postpro.rule_engine.footnote_rules import (
    FootnoteRulesResult,
    apply_footnote_rules,
)

_SPEC = CAPTURES["footnote_rules"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME

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
def result() -> FootnoteRulesResult:
    fx: dict[str, list[str | None]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    dataset = pl.DataFrame(
        {"footnotes": _series(fx["ds_footnotes"]), "unit": _series(fx["ds_unit"])}
    )
    rules = pl.DataFrame(
        {
            "column_source": _series(fx["r_cs"]),
            "value_source_raw": _series(fx["r_vsr"]),
            "value_source": _series(fx["r_vs"]),
            "column_target": _series(fx["r_ct"]),
            "value_target_raw": _series(fx["r_vtr"]),
            "value_target": _series(fx["r_vt"]),
        }
    )
    return apply_footnote_rules(
        dataset, rules, "clean", "whep", "rules.xlsx", "2026-01-01T00:00:00Z"
    )


@pytest.mark.parity
def test_reconstructed_columns_and_counts(result: FootnoteRulesResult) -> None:
    assert result.data.get_column("footnotes").to_list() == _gold("footnotes")
    assert result.data.get_column("unit").to_list() == _gold("unit")
    assert result.changed_value_count == int(_gold_scalar("changed"))
    assert list(result.changed_columns) == _gold("changed_columns")
    assert result.overwrite_events.height == int(_gold_scalar("overwrite_nrow"))


@pytest.mark.parity
def test_audit_table(result: FootnoteRulesResult) -> None:
    expected = pl.DataFrame(
        {
            "dataset_name": _gold("audit_dataset_name"),
            "column_source": _gold("audit_column_source"),
            "value_source_raw": _gold("audit_value_source_raw"),
            "value_source_result": _gold("audit_value_source_result"),
            "column_target": _gold("audit_column_target"),
            "value_target_raw": _gold("audit_value_target_raw"),
            "value_target_result": _gold("audit_value_target_result"),
            "affected_rows": [int(value) for value in _gold("audit_affected_rows") if value],
            "execution_timestamp_utc": _gold("audit_execution_timestamp_utc"),
            "rule_file_identifier": _gold("audit_rule_file_identifier"),
            "execution_stage": _gold("audit_execution_stage"),
        },
        schema=_AUDIT_SCHEMA,
    )
    assert_frame_equal(result.audit, expected, check_dtypes=True)
