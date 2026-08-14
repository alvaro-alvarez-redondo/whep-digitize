"""Unit tests for element-wise (token-level) rule matching and cell canonicalization.

Element-wise tokenization is the default matching mode for every data column: the source cell is
exploded on ``;``, each rule is evaluated against a single token, matching tokens are substituted
in place, and the cell is rebuilt deduplicated and sorted. ``#EXACT#`` opts a rule out and matches
the whole cell instead.

Covers the four contract areas: cell-internal ingestion canonicalization, element-wise
substitution, cross-column target updates, and ``#EXACT#`` full-cell behaviour.
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.rule_engine.payload_application import apply_rule_payload
from whep_digitize.postpro.rule_engine.schema_validation import coerce_rule_schema
from whep_digitize.postpro.utilities.templates import canonicalize_rule_token_cells
from whep_digitize.setup.helpers.strings import canonicalize_token_cell

_STAGE_COLUMNS = (
    "clean_column_source",
    "clean_value_source_raw",
    "clean_value_source",
    "clean_column_target",
    "clean_value_target_raw",
    "clean_value_target",
)
_TIMESTAMP = "2026-01-01T00:00:00Z"


def _rules(rows: list[dict[str, str | None]]) -> pl.DataFrame:
    raw = pl.DataFrame(
        {
            name: pl.Series(name, [row.get(name) for row in rows], dtype=pl.String)
            for name in _STAGE_COLUMNS
        }
    )
    return coerce_rule_schema(canonicalize_rule_token_cells(raw), "clean", "rules.xlsx")


def _rule(
    source_column: str,
    source_raw: str,
    source_value: str | None,
    target_column: str,
    target_raw: str | None,
    target_value: str | None,
) -> dict[str, str | None]:
    return {
        "clean_column_source": source_column,
        "clean_value_source_raw": source_raw,
        "clean_value_source": source_value,
        "clean_column_target": target_column,
        "clean_value_target_raw": target_raw,
        "clean_value_target": target_value,
    }


def _apply(dataset: pl.DataFrame, rows: list[dict[str, str | None]]) -> pl.DataFrame:
    return apply_rule_payload(dataset, _rules(rows), "clean", "whep", "r.xlsx", _TIMESTAMP).data


def _source_dataset(source_column: str, cell: str) -> pl.DataFrame:
    """A dataset with the source column plus an inert marker column for the rule's target."""
    return pl.DataFrame(
        {
            source_column: pl.Series(source_column, [cell], dtype=pl.String),
            "marker": pl.Series("marker", ["m"], dtype=pl.String),
        }
    )


def _source_rule(source_column: str, source_raw: str, source_value: str) -> dict[str, str | None]:
    """Rewrite a source token; the target write lands on the inert marker column."""
    return _rule(source_column, source_raw, source_value, "marker", "#ANY#", "m")


# ------------------------------------------------- 1. cell-internal ingestion canonicalization


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("c; a; b; a", "a; b; c"),  # split, trim, dedupe, sort, rejoin
        ("a; b; c", "a; b; c"),  # already canonical
        ("  d ;a ; c ", "a; c; d"),
        ("solo", "solo"),
        (" ; ; ", None),  # separators and whitespace only == missing data
        ("", None),
        (None, None),
    ],
)
def test_canonicalize_token_cell(raw: str | None, expected: str | None) -> None:
    assert canonicalize_token_cell(raw) == expected


def test_ingestion_canonicalizes_every_string_cell_independently() -> None:
    raw = pl.DataFrame(
        {
            "value_source_raw": pl.Series(["c; a; b", "z"], dtype=pl.String),
            "value_target_raw": pl.Series(["b; a", None], dtype=pl.String),
            "value_target": pl.Series(["y; x; y", "q"], dtype=pl.String),
        }
    )
    result = canonicalize_rule_token_cells(raw).to_dicts()
    assert result[0] == {
        "value_source_raw": "a; b; c",
        "value_target_raw": "a; b",
        "value_target": "x; y",
    }
    # Row 2 is untouched by row 1: canonicalization never mixes tokens across cells or rows.
    assert result[1] == {"value_source_raw": "z", "value_target_raw": None, "value_target": "q"}


def test_ingestion_keeps_the_exact_marker_at_the_start_of_the_cell() -> None:
    # Sorting the marker with the tokens would move it into the middle and break detection.
    raw = pl.DataFrame({"value_source_raw": pl.Series(["#EXACT#c; a"], dtype=pl.String)})
    assert canonicalize_rule_token_cells(raw).get_column("value_source_raw").to_list() == [
        "#EXACT#a; c"
    ]


# --------------------------------------------------------- 2. element-wise token substitution


def test_single_token_rule_substitutes_that_token_and_keeps_the_others() -> None:
    dataset = _source_dataset("hemisphere", "a; b; c; d")
    result = _apply(dataset, [_source_rule("hemisphere", "a", "z")])
    assert result.get_column("hemisphere").to_list() == ["b; c; d; z"]


def test_substituted_cell_is_deduplicated_and_sorted() -> None:
    # a -> c collides with the existing c; the rebuilt cell dedupes and sorts.
    dataset = _source_dataset("hemisphere", "a; b; c")
    result = _apply(dataset, [_source_rule("hemisphere", "a", "c")])
    assert result.get_column("hemisphere").to_list() == ["b; c"]


def test_several_tokens_substituted_independently_in_one_cell() -> None:
    dataset = _source_dataset("continent", "america north; america south; asia")
    result = _apply(
        dataset,
        [
            _source_rule("continent", "america north", "america"),
            _source_rule("continent", "america south", "america"),
        ],
    )
    # Both america tokens collapse to one; asia is preserved.
    assert result.get_column("continent").to_list() == ["america; asia"]


def test_non_matching_token_leaves_the_cell_untouched() -> None:
    dataset = _source_dataset("hemisphere", "a; b")
    result = _apply(dataset, [_source_rule("hemisphere", "zz", "z")])
    assert result.get_column("hemisphere").to_list() == ["a; b"]


# ------------------------------------------------------------------ 3. cross-column updates


def test_token_match_triggers_a_cross_column_target_update() -> None:
    """The spec scenario: a token rewrite on one column, conditioned update on another."""
    dataset = pl.DataFrame(
        {
            "hemisphere": pl.Series(["a; b; c; d"], dtype=pl.String),
            "continent": pl.Series(["europe"], dtype=pl.String),
        }
    )
    result = _apply(dataset, [_rule("hemisphere", "a", "z", "continent", "europe", "asia")])
    assert result.get_column("hemisphere").to_list() == ["b; c; d; z"]
    assert result.get_column("continent").to_list() == ["asia"]


def test_cross_column_update_is_skipped_when_the_condition_fails() -> None:
    dataset = pl.DataFrame(
        {
            "hemisphere": pl.Series(["a; b"], dtype=pl.String),
            "continent": pl.Series(["africa"], dtype=pl.String),
        }
    )
    result = _apply(dataset, [_rule("hemisphere", "a", "z", "continent", "europe", "asia")])
    # The target condition does not hold, so neither column is touched.
    assert result.get_column("hemisphere").to_list() == ["a; b"]
    assert result.get_column("continent").to_list() == ["africa"]


# ------------------------------------------------------------ 4. #EXACT# full-cell behaviour


def test_exact_rule_matches_the_whole_cell_and_replaces_it() -> None:
    dataset = _source_dataset("hemisphere", "a; b; c")
    result = _apply(dataset, [_source_rule("hemisphere", "#EXACT#a; b; c", "z")])
    assert result.get_column("hemisphere").to_list() == ["z"]


def test_exact_rule_does_not_match_a_single_token() -> None:
    dataset = _source_dataset("hemisphere", "a; b; c")
    result = _apply(dataset, [_source_rule("hemisphere", "#EXACT#a", "z")])
    assert result.get_column("hemisphere").to_list() == ["a; b; c"]


def test_plain_rule_does_not_match_the_whole_multi_token_cell() -> None:
    dataset = _source_dataset("hemisphere", "a; b; c")
    result = _apply(dataset, [_source_rule("hemisphere", "a; b; c", "z")])
    # Without #EXACT# the rule value is a token, and "a; b; c" is not one of the cell's tokens.
    assert result.get_column("hemisphere").to_list() == ["a; b; c"]


@pytest.mark.parametrize("marker", ["#EXACT#", "#exact#", "#Exact#"])
def test_exact_marker_is_case_insensitive(marker: str) -> None:
    dataset = _source_dataset("hemisphere", "a; b")
    result = _apply(dataset, [_source_rule("hemisphere", f"{marker}a; b", "z")])
    assert result.get_column("hemisphere").to_list() == ["z"]


def test_exact_rule_on_a_single_token_cell_still_matches() -> None:
    dataset = _source_dataset("hemisphere", "a")
    result = _apply(dataset, [_source_rule("hemisphere", "#EXACT#a", "z")])
    assert result.get_column("hemisphere").to_list() == ["z"]
