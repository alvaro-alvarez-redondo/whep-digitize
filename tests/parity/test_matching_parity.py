"""Parity test: rule-engine matching & value merge must match the frozen reference byte-for-byte.

Runs the matching helpers over the frozen
unicode / null / empty / wildcard / duplicate fixture and asserts they reproduce the
``match_rule_target_condition_values`` (tokenized + plain), ``encode_rule_match_key``,
``encode``/``decode_target_rule_value``, ``concatenate_existing_and_incoming_values``, and
``count_elementwise_value_changes``. This guards the two behaviors these functions hinge on:
null<->null folding to ``na_match_key``, and the diacritic fold applied inside match keys.

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_series_equal

from whep_digitize.postpro.rule_engine.matching_strategy import (
    decode_target_rule_value,
    encode_rule_match_key,
    encode_target_rule_value,
)
from whep_digitize.postpro.rule_engine.matching_values import (
    concatenate_existing_and_incoming_values,
    count_elementwise_value_changes,
    match_rule_target_condition_values,
)

_SPEC = GOLDENS["matching"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_CONCAT_DELIMITER = "; "  # matches the reference delimiter (the constant default)
_BOOL = {"TRUE": True, "FALSE": False}

# Python equivalent of each string-valued golden export.
_STRING_EXPORTS: dict[str, Callable[[dict[str, pl.Series]], pl.Series]] = {
    "encode_key": lambda columns: encode_rule_match_key(columns["current"]),
    "encode_key_raw": lambda columns: encode_rule_match_key(
        columns["target"], apply_normalization=False
    ),
    "encode_target": lambda columns: encode_target_rule_value(columns["target"]),
    "decode_target": lambda columns: decode_target_rule_value(
        encode_target_rule_value(columns["target"])
    ),
    "concat_merge": lambda columns: concatenate_existing_and_incoming_values(
        columns["existing"], columns["incoming"], _CONCAT_DELIMITER
    ),
}


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _gold_bool(name: str) -> list[bool]:
    return [_BOOL[value] for value in _gold(name) if value is not None]


@pytest.fixture(scope="module")
def columns() -> dict[str, pl.Series]:
    """The fixture as one string Series per argument column (the port's inputs)."""
    records = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return {
        key: pl.Series(key, [record[key] for record in records], dtype=pl.String)
        for key in records[0]
    }


@pytest.mark.parity
def test_match_tokenized_parity(columns: dict[str, pl.Series]) -> None:
    result = match_rule_target_condition_values(
        columns["current"], columns["condition"], tokenized_target=True
    )
    assert result.dtype == pl.Boolean
    assert result.to_list() == _gold_bool("match_tokenized")


@pytest.mark.parity
def test_match_plain_parity(columns: dict[str, pl.Series]) -> None:
    result = match_rule_target_condition_values(
        columns["current"], columns["condition"], tokenized_target=False
    )
    assert result.to_list() == _gold_bool("match_plain")


@pytest.mark.parity
@pytest.mark.parametrize("export", sorted(_STRING_EXPORTS))
def test_string_exports_parity(export: str, columns: dict[str, pl.Series]) -> None:
    expected = pl.Series(export, _gold(export), dtype=pl.String)
    result = _STRING_EXPORTS[export](columns).rename(export)
    assert_series_equal(result, expected, check_dtypes=True, check_names=True)


@pytest.mark.parity
def test_change_count_parity(columns: dict[str, pl.Series]) -> None:
    expected = _gold("change_count")[0]
    assert expected is not None
    result = count_elementwise_value_changes(columns["before"], columns["after"])
    assert result == int(expected)
