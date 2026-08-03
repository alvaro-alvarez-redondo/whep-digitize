"""Parity test: rule-file loading + layer diagnostics must match the R golden.

Exercises the port of ``21-template-rules.R`` (``read_rule_table``) and ``21-diagnostics.R``
(``build_layer_diagnostics``) over the committed xlsx rule fixture and asserts:

* ``read_rule_table`` (xlsx) — the ``clean_`` prefix is stripped, only the canonical-schema-matching
  sheet is kept (the ``guidance`` sheet is skipped), and every cell is read all-as-text so
  ``"007"`` / ``"1000.0"`` keep their exact source string.
* ``read_rule_table`` (csv, DB2) — readr's ``col_character`` + default ``na = c("", "NA")``: both
  empty cells and the literal ``"NA"`` become null, while ``"007"`` and a quoted ``"a,b"`` survive.
* ``build_layer_diagnostics`` — the deterministic matched/unmatched counts, status, and message
  for a matched and an empty audit table (the wall-clock timestamp is not reproduced).

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.utilities.diagnostics import build_layer_diagnostics
from whep_digitize.postpro.utilities.templates import read_rule_table

_SPEC = GOLDENS["utilities"]
_CSV_SPEC = GOLDENS["rule_table_csv"]
_RULE_FIXTURE = FIXTURES_DIR / "synthetic" / "clean_rules_sample.xlsx"
_CSV_FIXTURE = FIXTURES_DIR / "synthetic" / "rule_table_sample.csv"


def _read_gold(path: Path, module: str) -> list[str | None]:
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with `python tests/parity/capture.py {module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _gold(name: str) -> list[str | None]:
    return _read_gold(_SPEC.golden_paths()[name], _SPEC.module)


def _csv_gold(name: str) -> list[str | None]:
    return _read_gold(_CSV_SPEC.golden_paths()[name], _CSV_SPEC.module)


@pytest.mark.parity
def test_read_rule_table_matches_golden() -> None:
    rules = read_rule_table(_RULE_FIXTURE)
    assert rules.columns == _gold("rr_columns")
    assert [str(rules.height)] == _gold("rr_nrow")
    assert rules.get_column("column_source").to_list() == _gold("rr_column_source")
    assert rules.get_column("value_source_raw").to_list() == _gold("rr_value_source_raw")
    assert rules.get_column("value_source").to_list() == _gold("rr_value_source")
    assert rules.get_column("column_target").to_list() == _gold("rr_column_target")
    assert rules.get_column("value_target_raw").to_list() == _gold("rr_value_target_raw")
    assert rules.get_column("value_target").to_list() == _gold("rr_value_target")


@pytest.mark.parity
def test_read_rule_table_csv_matches_golden() -> None:
    rules = read_rule_table(_CSV_FIXTURE)
    assert rules.columns == _csv_gold("columns")
    assert [str(rules.height)] == _csv_gold("nrow")
    assert rules.get_column("column_source").to_list() == _csv_gold("column_source")
    # readr default na = c("", "NA"): the empty cell and the literal "NA" both read as null.
    assert rules.get_column("value_source_raw").to_list() == _csv_gold("value_source_raw")
    assert rules.get_column("value_target_raw").to_list() == _csv_gold("value_target_raw")


@pytest.mark.parity
def test_build_layer_diagnostics_matches_golden() -> None:
    matched = build_layer_diagnostics(
        "clean", 10, 10, pl.DataFrame({"affected_rows": pl.Series([2, 3], dtype=pl.Int64)})
    )
    assert [str(matched.matched_count)] == _gold("diag_matched_matched_count")
    assert [str(matched.unmatched_count)] == _gold("diag_matched_unmatched_count")
    assert [matched.status] == _gold("diag_matched_status")
    assert list(matched.messages) == _gold("diag_matched_messages")

    empty = build_layer_diagnostics(
        "clean", 5, 5, pl.DataFrame({"affected_rows": pl.Series([], dtype=pl.Int64)})
    )
    assert [str(empty.matched_count)] == _gold("diag_empty_matched_count")
    assert [str(empty.unmatched_count)] == _gold("diag_empty_unmatched_count")
    assert [empty.status] == _gold("diag_empty_status")
    assert list(empty.messages) == _gold("diag_empty_messages")
