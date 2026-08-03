"""Unit tests for the postpro rule-engine footnote-rule application.

Covers :mod:`whep_digitize.postpro.rule_engine.footnote_rules`. Byte
parity is covered in ``tests/parity/test_footnote_rules_parity.py``; these tests pin the
behavioral contract (explode / match / resolve / reconstruct, precedence, change counting,
audit, validation).
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.rule_engine.footnote_rules import (
    FootnoteRulesResult,
    apply_footnote_rules,
)
from whep_digitize.setup.errors import ValidationError

_RULE_COLUMNS = (
    "column_source",
    "value_source_raw",
    "value_source",
    "column_target",
    "value_target_raw",
    "value_target",
)


def _rules(rows: list[tuple[str | None, ...]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            name: pl.Series(name, [row[i] for row in rows], dtype=pl.String)
            for i, name in enumerate(_RULE_COLUMNS)
        }
    )


def _dataset(footnotes: list[str | None], unit: list[str | None] | None = None) -> pl.DataFrame:
    columns = {"footnotes": pl.Series("footnotes", footnotes, dtype=pl.String)}
    if unit is not None:
        columns["unit"] = pl.Series("unit", unit, dtype=pl.String)
    return pl.DataFrame(columns)


def _apply(dataset: pl.DataFrame, rules: pl.DataFrame) -> FootnoteRulesResult:
    return apply_footnote_rules(
        dataset, rules, "clean", "whep", "rules.xlsx", "2026-01-01T00:00:00Z"
    )


def test_replace_footnote_token() -> None:
    result = _apply(
        _dataset(["old"]), _rules([("footnotes", "old", "new", "footnotes", None, None)])
    )
    assert result.data.get_column("footnotes").to_list() == ["new"]
    assert result.changed_columns == ("footnotes",)


def test_remove_footnote_token() -> None:
    result = _apply(
        _dataset(["drop"]), _rules([("footnotes", "drop", None, "footnotes", None, None)])
    )
    assert result.data.get_column("footnotes").to_list() == [None]


def test_multi_token_partial_replace() -> None:
    result = _apply(
        _dataset(["a; b; c"]), _rules([("footnotes", "b", "B", "footnotes", None, None)])
    )
    # a, c unmatched (kept); b replaced -> "a; B; c".
    assert result.data.get_column("footnotes").to_list() == ["a; B; c"]


def test_precedence_remove_beats_replace() -> None:
    result = _apply(
        _dataset(["x"]),
        _rules(
            [
                ("footnotes", "x", "R", "footnotes", None, None),
                ("footnotes", "x", None, "footnotes", None, None),
            ]
        ),
    )
    # One rule replaces x->R, another removes x; remove wins -> NA.
    assert result.data.get_column("footnotes").to_list() == [None]


def test_precedence_first_replacement_wins() -> None:
    result = _apply(
        _dataset(["x"]),
        _rules(
            [
                ("footnotes", "x", "FIRST", "footnotes", None, None),
                ("footnotes", "x", "SECOND", "footnotes", None, None),
            ]
        ),
    )
    assert result.data.get_column("footnotes").to_list() == ["FIRST"]


def test_na_footnote_matched_by_na_rule_replaces() -> None:
    result = _apply(
        _dataset([None]), _rules([("footnotes", None, "FILLED", "footnotes", None, None)])
    )
    # NA footnote -> one NA token -> matches the NA-source rule -> replaced.
    assert result.data.get_column("footnotes").to_list() == ["FILLED"]


def test_na_footnote_unmatched_stays_na() -> None:
    result = _apply(_dataset([None]), _rules([("footnotes", "x", "X", "footnotes", None, None)]))
    assert result.data.get_column("footnotes").to_list() == [None]


def test_empty_string_footnote_becomes_na() -> None:
    result = _apply(_dataset([""]), _rules([("footnotes", "x", "X", "footnotes", None, None)]))
    assert result.data.get_column("footnotes").to_list() == [None]


def test_trailing_semicolon_token_dropped() -> None:
    # A single trailing empty field is dropped: "a;" -> ["a"].
    result = _apply(_dataset(["a;"]), _rules([("footnotes", "a", "A", "footnotes", None, None)]))
    assert result.data.get_column("footnotes").to_list() == ["A"]


def test_whitespace_token_is_trimmed_for_matching() -> None:
    result = _apply(
        _dataset([" a ; b"]), _rules([("footnotes", "a", "A", "footnotes", None, None)])
    )
    assert result.data.get_column("footnotes").to_list() == ["A; b"]


def test_transliteration_match() -> None:
    result = _apply(
        _dataset(["Café"]), _rules([("footnotes", "cafe", "COFFEE", "footnotes", None, None)])
    )
    assert result.data.get_column("footnotes").to_list() == ["COFFEE"]


def test_noop_replacement_marks_nothing_changed() -> None:
    result = _apply(
        _dataset(["same"]), _rules([("footnotes", "same", "same", "footnotes", None, None)])
    )
    assert result.data.get_column("footnotes").to_list() == ["same"]
    assert result.changed_columns == ()
    assert result.audit.height == 0


def test_conditional_target_applies_when_condition_matches() -> None:
    result = _apply(
        _dataset(["fn"], unit=["kg"]),
        _rules([("footnotes", "fn", None, "unit", "kg", "tonne")]),
    )
    # Condition (unit == "kg") matches -> unit updated, footnote removed.
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.data.get_column("footnotes").to_list() == [None]
    assert result.changed_columns == ("footnotes", "unit")


def test_conditional_target_skipped_when_condition_fails() -> None:
    result = _apply(
        _dataset(["fn"], unit=["g"]),
        _rules([("footnotes", "fn", None, "unit", "kg", "tonne")]),
    )
    # Condition fails (unit "g" != "kg") -> nothing applied; footnote kept.
    assert result.data.get_column("unit").to_list() == ["g"]
    assert result.data.get_column("footnotes").to_list() == ["fn"]
    assert result.changed_columns == ()


def test_target_only_change_does_not_mark_footnotes() -> None:
    # A rule that keeps the footnote text (value_source == the footnote) but updates a target.
    result = _apply(
        _dataset(["fn"], unit=["kg"]),
        _rules([("footnotes", "fn", "fn", "unit", "kg", "tonne")]),
    )
    assert result.data.get_column("footnotes").to_list() == ["fn"]
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.changed_columns == ("unit",)


def test_affected_rows_counts_all_matching_tokens() -> None:
    result = _apply(
        _dataset(["a", "a; a", "b"]),
        _rules([("footnotes", "a", "A", "footnotes", None, None)]),
    )
    assert result.audit.height == 1
    assert result.audit.get_column("value_source_raw").to_list() == ["a"]
    # "a" appears in row 1 (once) and row 2 (twice) -> 3 matched tokens.
    assert result.audit.get_column("affected_rows").to_list() == [3]
    assert result.data.get_column("footnotes").to_list() == ["A", "A; A", "b"]


def test_footnotes_column_added_when_absent() -> None:
    result = _apply(
        pl.DataFrame({"unit": pl.Series("unit", ["kg"], dtype=pl.String)}),
        _rules([("footnotes", "x", "X", "footnotes", None, None)]),
    )
    assert "footnotes" in result.data.columns
    assert result.data.get_column("footnotes").to_list() == [None]


def test_empty_rules_raises() -> None:
    with pytest.raises(ValidationError):
        _apply(_dataset(["a"]), _rules([]))


def test_empty_string_argument_raises() -> None:
    with pytest.raises(ValidationError):
        apply_footnote_rules(
            _dataset(["a"]),
            _rules([("footnotes", "a", "A", "footnotes", None, None)]),
            "clean",
            "",
            "rules.xlsx",
            "2026-01-01T00:00:00Z",
        )
