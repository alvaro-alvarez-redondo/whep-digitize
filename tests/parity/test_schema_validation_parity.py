"""Parity test: rule-schema coercion, validation, and dictionary must match the R golden.

Exercises the port of ``23-schema-validation.R`` over a frozen fixture and asserts:

* ``build_conditional_rule_dictionary`` grouping — the flattened groups encode both the group
  order (R ``interaction`` factor order) and the within-group radix / code-point + NA-last order
  that feeds ``last_rule_wins`` (parity risk #7).
* ``coerce_rule_schema`` — canonical column set/order, the ``source_value_column_present`` flag,
  and the synthesized-when-absent ``value_source`` column.
* ``validate_canonical_rules`` abort behavior — valid rules pass; duplicate keys and
  missing dataset columns abort (captured from R with ``try()``).

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.rule_engine.schema_validation import (
    build_conditional_rule_dictionary,
    coerce_rule_schema,
    validate_canonical_rules,
)
from whep_digitize.setup.errors import ValidationError

_SPEC = GOLDENS["schema_validation"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_BOOL = {"TRUE": True, "FALSE": False}


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with "
            f"`python tests/parity/capture.py {_SPEC.module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _gold_bool(name: str) -> list[bool]:
    return [_BOOL[value] for value in _gold(name) if value is not None]


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, list[str | None]]:
    data: dict[str, list[str | None]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def _series(values: list[str | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


def _rules(fixture_data: dict[str, list[str | None]], prefix: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "column_source": _series(fixture_data[f"{prefix}_cs"]),
            "value_source_raw": _series(fixture_data[f"{prefix}_vsr"]),
            "value_source": _series(fixture_data[f"{prefix}_vs"]),
            "column_target": _series(fixture_data[f"{prefix}_ct"]),
            "value_target_raw": _series(fixture_data[f"{prefix}_vtr"]),
            "value_target": _series(fixture_data[f"{prefix}_vt"]),
        }
    )


@pytest.mark.parity
def test_dictionary_grouping_and_order(fixture_data: dict[str, list[str | None]]) -> None:
    groups = build_conditional_rule_dictionary(_rules(fixture_data, "dict"), "clean")
    assert str(len(groups)) == _gold("dict_ngroups")[0]

    flat = pl.concat(groups)
    assert flat.get_column("column_source").to_list() == _gold("dict_flat_column_source")
    assert flat.get_column("column_target").to_list() == _gold("dict_flat_column_target")
    assert flat.get_column("value_source_raw").to_list() == _gold("dict_flat_value_source_raw")
    assert flat.get_column("value_target").to_list() == _gold("dict_flat_value_target")


@pytest.mark.parity
def test_coerce_with_value_source_present(fixture_data: dict[str, list[str | None]]) -> None:
    coerced = coerce_rule_schema(
        pl.DataFrame(
            {
                "clean_value_target": _series(fixture_data["cA_vt"]),
                "clean_column_source": _series(fixture_data["cA_cs"]),
                "clean_value_target_raw": _series(fixture_data["cA_vtr"]),
                "clean_value_source": _series(fixture_data["cA_vs"]),
                "clean_column_target": _series(fixture_data["cA_ct"]),
                "clean_value_source_raw": _series(fixture_data["cA_vsr"]),
            }
        ),
        "clean",
        "rulesA.xlsx",
    )
    assert coerced.columns == _gold("cA_columns")
    assert coerced.get_column("source_value_column_present").to_list() == _gold_bool(
        "cA_source_value_column_present"
    )
    assert coerced.get_column("value_source").to_list() == _gold("cA_value_source")
    assert coerced.get_column("column_source").to_list() == _gold("cA_column_source")


@pytest.mark.parity
def test_coerce_with_value_source_absent(fixture_data: dict[str, list[str | None]]) -> None:
    coerced = coerce_rule_schema(
        pl.DataFrame(
            {
                "clean_column_source": _series(fixture_data["cB_cs"]),
                "clean_value_source_raw": _series(fixture_data["cB_vsr"]),
                "clean_column_target": _series(fixture_data["cB_ct"]),
                "clean_value_target_raw": _series(fixture_data["cB_vtr"]),
                "clean_value_target": _series(fixture_data["cB_vt"]),
            }
        ),
        "clean",
        "rulesB.xlsx",
    )
    assert coerced.columns == _gold("cB_columns")
    assert coerced.get_column("source_value_column_present").to_list() == _gold_bool(
        "cB_source_value_column_present"
    )
    assert coerced.get_column("value_source").to_list() == _gold("cB_value_source")


@pytest.mark.parity
@pytest.mark.parametrize(
    ("prefix", "golden"),
    [
        ("v", "validate_valid_aborts"),
        ("dup", "validate_duplicate_aborts"),
        ("mc", "validate_missing_column_aborts"),
    ],
)
def test_validate_abort_behavior(
    fixture_data: dict[str, list[str | None]], prefix: str, golden: str
) -> None:
    dataset = pl.DataFrame(
        {
            "commodity": _series(fixture_data["ds_commodity"]),
            "unit": _series(fixture_data["ds_unit"]),
            "continent": _series(fixture_data["ds_continent"]),
        }
    )
    aborted = False
    try:
        validate_canonical_rules(_rules(fixture_data, prefix), dataset, "rules.xlsx", "clean")
    except ValidationError:
        aborted = True
    assert aborted == _gold_bool(golden)[0]
