"""Unit tests for the postpro rule-engine conditional rule-group application.

Covers :mod:`whep_digitize.postpro.rule_engine.conditional_group`.
Reference parity is covered in ``tests/parity/test_conditional_group_parity.py``; these tests pin
the behavioral contract (source/target scatter, independent changed_columns, audit table,
overwrite events, argument validation).
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.rule_engine.conditional_group import (
    ConditionalGroupResult,
    PreparedConditionalGroup,
    apply_conditional_rule_group,
    prepare_conditional_rule_group,
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


def _group(
    rows: list[tuple[str | None, ...]], *, present: list[bool] | None = None
) -> pl.DataFrame:
    frame = pl.DataFrame(
        {
            name: pl.Series(name, [row[i] for row in rows], dtype=pl.String)
            for i, name in enumerate(_RULE_COLUMNS)
        }
    )
    flags = present if present is not None else [row[2] is not None for row in rows]
    return frame.with_columns(pl.Series("source_value_column_present", flags, dtype=pl.Boolean))


def _dataset(**columns: list[str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in columns.items()}
    )


def _apply(
    dataset: pl.DataFrame,
    *,
    group_rules: pl.DataFrame | None = None,
    prepared_group: PreparedConditionalGroup | None = None,
    dataset_name: str = "whep",
) -> ConditionalGroupResult:
    """Call the port with fixed labels (the arguments under test vary per test)."""
    return apply_conditional_rule_group(
        dataset,
        group_rules=group_rules,
        prepared_group=prepared_group,
        stage_name="clean",
        dataset_name=dataset_name,
        rule_file_id="rules.xlsx",
        execution_timestamp_utc="2026-01-01T00:00:00Z",
    )


def test_source_and_target_both_change() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["RICE"]
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.changed_value_count == 2
    assert result.changed_columns == ("commodity", "unit")


def test_source_only_rewrite_does_not_mark_target() -> None:
    # value_target equals the current unit -> the target update is a no-op; only the source changes.
    dataset = _dataset(commodity=["wheat"], unit=["kg"])
    group = _group([("commodity", "wheat", "WHEAT", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["WHEAT"]
    assert result.data.get_column("unit").to_list() == ["kg"]
    assert result.changed_value_count == 1
    assert result.changed_columns == ("commodity",)


def test_target_only_when_source_value_absent() -> None:
    dataset = _dataset(commodity=["maize"], unit=["kg"])
    group = _group([("commodity", "maize", None, "unit", "kg", "tonne")], present=[False])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["maize"]
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.changed_columns == ("unit",)


def test_no_match_changes_nothing() -> None:
    dataset = _dataset(commodity=["barley"], unit=["kg"])
    group = _group([("commodity", "wheat", "WHEAT", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["barley"]
    assert result.changed_value_count == 0
    assert result.changed_columns == ()
    assert result.audit.height == 0


def test_target_condition_must_match_current_value() -> None:
    # The rule's target condition ("kg") does not match the current unit ("g") -> no application.
    dataset = _dataset(commodity=["rice"], unit=["g"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.changed_value_count == 0
    assert result.data.get_column("commodity").to_list() == ["rice"]


def test_transliteration_source_match() -> None:
    dataset = _dataset(commodity=["Café"], unit=["kg"])
    group = _group([("commodity", "cafe", "COFFEE", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["COFFEE"]
    assert result.data.get_column("unit").to_list() == ["tonne"]


def test_audit_groups_and_counts_affected_rows() -> None:
    dataset = _dataset(commodity=["wheat", "wheat", "rye"], unit=["kg", "kg", "kg"])
    group = _group(
        [
            ("commodity", "wheat", "WHEAT", "unit", "kg", "tonne"),
            ("commodity", "rye", "RYE", "unit", "kg", "gram"),
        ]
    )
    result = _apply(dataset, group_rules=group)
    audit = result.audit
    assert audit.height == 2
    # Ordered by value_source_raw: "rye" before "wheat".
    assert audit.get_column("value_source_raw").to_list() == ["rye", "wheat"]
    assert audit.get_column("affected_rows").to_list() == [1, 2]
    assert audit.get_column("dataset_name").to_list() == ["whep", "whep"]
    assert audit.get_column("execution_stage").to_list() == ["clean", "clean"]


def test_concatenate_target_column() -> None:
    dataset = _dataset(commodity=["rice"], notes=["a; b"])
    group = _group([("commodity", "rice", None, "notes", "#ANY#", "b; c")], present=[False])
    result = _apply(dataset, group_rules=group)
    # notes uses the concatenate strategy: existing "a; b" merged with "b; c" -> "a; b; c".
    assert result.data.get_column("notes").to_list() == ["a; b; c"]
    assert result.changed_columns == ("notes",)


def test_conflicting_target_rules_last_wins() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group(
        [
            ("commodity", "rice", None, "unit", "kg", "tonne"),
            ("commodity", "rice", None, "unit", "kg", "gram"),
        ],
        present=[False, False],
    )
    result = _apply(dataset, group_rules=group)
    # Two rules target the same token ("kg") -> last-rule-wins at token level (D7).
    assert result.data.get_column("unit").to_list() == ["gram"]


def test_prepared_group_path() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    prepared = prepare_conditional_rule_group(
        _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")]), "clean"
    )
    result = _apply(dataset, prepared_group=prepared)
    assert result.data.get_column("commodity").to_list() == ["RICE"]


def test_requires_exactly_one_of_group_or_prepared() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    prepared = prepare_conditional_rule_group(group, "clean")
    with pytest.raises(ValidationError):
        _apply(dataset)
    with pytest.raises(ValidationError):
        _apply(dataset, group_rules=group, prepared_group=prepared)


def test_empty_string_argument_raises() -> None:
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "rice", "RICE", "unit", "kg", "tonne")])
    with pytest.raises(ValidationError):
        _apply(dataset, group_rules=group, dataset_name="")


def test_prepare_rejects_empty_group() -> None:
    empty = _group([]).clear()
    with pytest.raises(ValidationError):
        prepare_conditional_rule_group(empty, "clean")


# ── Symmetric target tokenization tests (DECISIONS.md) ──────────────────────────


def test_target_token_substitution_preserves_siblings() -> None:
    """D5: single token substitution preserves sibling tokens."""
    dataset = _dataset(commodity=["rice"], unit=["a; b; c"])
    group = _group([("commodity", "rice", None, "unit", "b", "B")], present=[False])
    result = _apply(dataset, group_rules=group)
    # Only "b" → "B"; siblings "a" and "c" preserved; canonicalized (sorted).
    assert result.data.get_column("unit").to_list() == ["B; a; c"]
    assert result.changed_columns == ("unit",)


def test_target_multiple_token_substitutions() -> None:
    """D5 + D7: two rules targeting different tokens both apply."""
    dataset = _dataset(commodity=["rice"], unit=["a; b; c"])
    group = _group(
        [
            ("commodity", "rice", None, "unit", "a", "A"),
            ("commodity", "rice", None, "unit", "c", "C"),
        ],
        present=[False, False],
    )
    result = _apply(dataset, group_rules=group)
    # "a" → "A" and "c" → "C"; "b" preserved; sorted.
    assert result.data.get_column("unit").to_list() == ["A; C; b"]
    assert result.changed_columns == ("unit",)


def test_target_any_adds_token() -> None:
    """D3: #ANY# adds a new token without replacing existing tokens."""
    dataset = _dataset(commodity=["rice"], unit=["a; b"])
    group = _group(
        [("commodity", "rice", None, "unit", "#ANY#", "c")], present=[False]
    )
    result = _apply(dataset, group_rules=group)
    # "c" added to existing "a; b"; sorted and deduplicated.
    assert result.data.get_column("unit").to_list() == ["a; b; c"]
    assert result.changed_columns == ("unit",)


def test_target_any_deduplicates() -> None:
    """D3: #ANY# does not duplicate an existing token."""
    dataset = _dataset(commodity=["rice"], unit=["a; b"])
    group = _group(
        [("commodity", "rice", None, "unit", "#ANY#", "a")], present=[False]
    )
    result = _apply(dataset, group_rules=group)
    # "a" already present -> no change.
    assert result.data.get_column("unit").to_list() == ["a; b"]
    assert result.changed_value_count == 0


def test_target_exact_rewrites_cell() -> None:
    """D2: #EXACT# rewrites the entire target cell, bypassing tokenization."""
    dataset = _dataset(commodity=["rice"], unit=["a; b; c"])
    group = _group(
        [("commodity", "rice", None, "unit", "#EXACT# a; b; c", "X")], present=[False]
    )
    result = _apply(dataset, group_rules=group)
    # Full cell override: "a; b; c" → "X".
    assert result.data.get_column("unit").to_list() == ["X"]
    assert result.changed_columns == ("unit",)


def test_target_same_token_last_rule_wins() -> None:
    """D7: when two rules match the same token, last rule wins at token level."""
    dataset = _dataset(commodity=["rice"], unit=["a; b"])
    group = _group(
        [
            ("commodity", "rice", None, "unit", "a", "A"),
            ("commodity", "rice", None, "unit", "a", "AA"),
        ],
        present=[False, False],
    )
    result = _apply(dataset, group_rules=group)
    # Rule 2 wins for token "a" -> "AA"; "b" preserved.
    assert result.data.get_column("unit").to_list() == ["AA; b"]
    assert result.changed_columns == ("unit",)


def test_target_none_condition_only_matches_na() -> None:
    """D4: value_target_raw=None matches only NA cells, not populated cells."""
    rule = ("commodity", "rice", None, "unit", None, "X")

    # Non-NA target: rule does not match.
    dataset_a = _dataset(commodity=["rice"], unit=["a"])
    group_a = _group([rule], present=[False])
    result_a = _apply(dataset_a, group_rules=group_a)
    assert result_a.data.get_column("unit").to_list() == ["a"]
    assert result_a.changed_value_count == 0

    # NA target: rule matches and applies.
    dataset_na = _dataset(commodity=["rice"], unit=[None])
    group_na = _group([rule], present=[False])
    result_na = _apply(dataset_na, group_rules=group_na)
    assert result_na.data.get_column("unit").to_list() == ["X"]
    assert result_na.changed_columns == ("unit",)


def test_source_none_condition_matches_na_source() -> None:
    """D10: value_source_raw=None matches only NA source cells (symmetric to D4).

    A rule with value_source_raw=None should match rows where the source column
    is NULL/NA, then apply the source rewrite and target condition normally.
    """
    # Rule: when source is NULL and target is "asia, europe",
    # fill source with "asia; europe" and clear target.
    rule = ("continent", None, "asia; europe", "footnotes", "asia, europe", None)

    # NA source + matching target condition: rule fires.
    dataset_match = _dataset(continent=[None], footnotes=["asia, europe"])
    group_match = _group([rule], present=[True])
    result_match = _apply(dataset_match, group_rules=group_match)
    assert result_match.data.get_column("continent").to_list() == ["asia; europe"]
    assert result_match.data.get_column("footnotes").to_list() == [None]
    assert result_match.changed_columns == ("continent", "footnotes")

    # NA source + non-matching target condition: rule does not fire.
    dataset_no_target = _dataset(continent=[None], footnotes=["other"])
    group_no_target = _group([rule], present=[True])
    result_no_target = _apply(dataset_no_target, group_rules=group_no_target)
    assert result_no_target.data.get_column("continent").to_list() == [None]
    assert result_no_target.changed_value_count == 0

    # Non-NA source: rule does not match.
    dataset_non_na = _dataset(continent=["asia"], footnotes=["asia, europe"])
    group_non_na = _group([rule], present=[True])
    result_non_na = _apply(dataset_non_na, group_rules=group_non_na)
    assert result_non_na.data.get_column("continent").to_list() == ["asia"]
    assert result_non_na.changed_value_count == 0


def test_source_target_symmetric() -> None:
    """Symmetric tokenization: source and target both substitute tokens independently."""
    dataset = _dataset(commodity=["a; b; c"], unit=["x; y; z"])
    group = _group([("commodity", "a", "A", "unit", "y", "Y")])
    result = _apply(dataset, group_rules=group)
    # Source: "a" → "A", siblings "b; c" preserved.
    assert result.data.get_column("commodity").to_list() == ["A; b; c"]
    # Target: "y" → "Y", siblings "x; z" preserved.
    assert result.data.get_column("unit").to_list() == ["Y; x; z"]
    assert result.changed_columns == ("commodity", "unit")


def test_concatenate_column_unchanged() -> None:
    """D8: columns configured with 'concatenate' (e.g., notes) still use concatenate strategy."""
    dataset = _dataset(commodity=["rice"], notes=["a; b"])
    group = _group(
        [("commodity", "rice", None, "notes", "#ANY#", "b; c")], present=[False]
    )
    result = _apply(dataset, group_rules=group)
    # Concatenate merges token sets: {"a", "b"} U {"b", "c"} = {"a", "b", "c"}.
    assert result.data.get_column("notes").to_list() == ["a; b; c"]
    assert result.changed_columns == ("notes",)


# ── Source #ANY# wildcard tests (D3) ─────────────────────────────────────────────


def test_source_any_adds_token() -> None:
    """D3: #ANY# in source adds a new token without replacing existing tokens."""
    dataset = _dataset(commodity=["a; b"], unit=["kg"])
    group = _group([("commodity", "#ANY#", "c", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    # "c" added to existing "a; b"; sorted and deduplicated.
    assert result.data.get_column("commodity").to_list() == ["a; b; c"]
    assert result.changed_columns == ("commodity",)


def test_source_any_deduplicates() -> None:
    """D3: #ANY# source does not duplicate an existing token."""
    dataset = _dataset(commodity=["a; b"], unit=["kg"])
    group = _group([("commodity", "#ANY#", "a", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    # "a" already present -> no change.
    assert result.data.get_column("commodity").to_list() == ["a; b"]
    assert result.changed_value_count == 0


def test_source_any_single_token_source() -> None:
    """D3: #ANY# source works with a single-token source cell."""
    dataset = _dataset(commodity=["rice"], unit=["kg"])
    group = _group([("commodity", "#ANY#", "wheat", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    # "wheat" added to existing "rice"; sorted.
    assert result.data.get_column("commodity").to_list() == ["rice; wheat"]
    assert result.changed_columns == ("commodity",)


def test_source_any_with_target_rewrite() -> None:
    """D3: #ANY# source adds token while target also rewrites."""
    dataset = _dataset(commodity=["a; b"], unit=["kg"])
    group = _group([("commodity", "#ANY#", "c", "unit", "kg", "tonne")])
    result = _apply(dataset, group_rules=group)
    # Source: "a; b" + "c" -> "a; b; c"
    # Target: "kg" -> "tonne"
    assert result.data.get_column("commodity").to_list() == ["a; b; c"]
    assert result.data.get_column("unit").to_list() == ["tonne"]
    assert result.changed_columns == ("commodity", "unit")


def test_source_any_case_insensitive() -> None:
    """D3: #ANY# source marker is case-insensitive."""
    dataset = _dataset(commodity=["a; b"], unit=["kg"])
    group = _group([("commodity", "#any#", "c", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    assert result.data.get_column("commodity").to_list() == ["a; b; c"]
    assert result.changed_columns == ("commodity",)


def test_source_any_empty_source() -> None:
    """D3: #ANY# source adds token even when source cell is empty."""
    dataset = _dataset(commodity=[""], unit=["kg"])
    group = _group([("commodity", "#ANY#", "c", "unit", "kg", "kg")])
    result = _apply(dataset, group_rules=group)
    # Empty source + "c" -> "c".
    assert result.data.get_column("commodity").to_list() == ["c"]
    assert result.changed_columns == ("commodity",)


def test_source_any_multiple_rules() -> None:
    """D3: multiple #ANY# source rules add multiple tokens."""
    dataset = _dataset(commodity=["a"], unit=["kg"])
    group = _group(
        [
            ("commodity", "#ANY#", "b", "unit", "kg", "kg"),
            ("commodity", "#ANY#", "c", "unit", "kg", "kg"),
        ]
    )
    result = _apply(dataset, group_rules=group)
    # "a" + "b" + "c" -> "a; b; c" (sorted, deduplicated).
    assert result.data.get_column("commodity").to_list() == ["a; b; c"]
    assert result.changed_columns == ("commodity",)


# ── #EXACT# source does not leak to target (bug fix) ──────────────────────────


def test_exact_source_does_not_leak_to_target_token_substitution() -> None:
    """#EXACT# in source should not cause full-cell override on target.

    Source 'ass; horse; mule' with #EXACT# rule -> full cell override to 'horse'.
    Target 'horse; latin america' with normal token match on 'horse' -> substitute
    'horse' token only, preserve 'latin america' sibling.
    """
    dataset = _dataset(
        commodity=["ass; horse; mule"],
        footnotes=["horse; latin america"],
    )
    group = _group(
        [
            (
                "commodity",
                "#EXACT# ass; horse; mule",
                "horse",
                "footnotes",
                "horse",
                "--temporal--horse",
            )
        ]
    )
    result = _apply(dataset, group_rules=group)
    # Source: full-cell override (correct — #EXACT# in source).
    assert result.data.get_column("commodity").to_list() == ["horse"]
    # Target: token substitution only — 'horse' replaced, 'latin america' preserved.
    assert result.data.get_column("footnotes").to_list() == [
        "--temporal--horse; latin america"
    ]
    assert result.changed_columns == ("commodity", "footnotes")


def test_exact_source_exact_target_both_full_cell() -> None:
    """When both source AND target have #EXACT#, both sides do full-cell override."""
    dataset = _dataset(
        commodity=["ass; horse; mule"],
        footnotes=["horse; latin america"],
    )
    group = _group(
        [
            (
                "commodity",
                "#EXACT# ass; horse; mule",
                "horse",
                "footnotes",
                "#EXACT# horse; latin america",
                "--temporal--horse",
            )
        ]
    )
    result = _apply(dataset, group_rules=group)
    # Both sides: full-cell override.
    assert result.data.get_column("commodity").to_list() == ["horse"]
    assert result.data.get_column("footnotes").to_list() == ["--temporal--horse"]
    assert result.changed_columns == ("commodity", "footnotes")


def test_exact_source_normal_target_preserves_all_siblings() -> None:
    """#EXACT# source + normal target: multiple sibling tokens preserved."""
    dataset = _dataset(
        commodity=["a; b; c"],
        unit=["x; y; z"],
    )
    group = _group(
        [
            ("commodity", "#EXACT# a; b; c", "REPLACED", "unit", "y", "Y")
        ]
    )
    result = _apply(dataset, group_rules=group)
    # Source: full-cell override.
    assert result.data.get_column("commodity").to_list() == ["REPLACED"]
    # Target: only 'y' -> 'Y'; 'x' and 'z' preserved; tokens sorted.
    assert result.data.get_column("unit").to_list() == ["Y; x; z"]


def test_exact_source_any_target() -> None:
    """#EXACT# in source + #ANY# in target: source full-cell override, target adds token."""
    dataset = _dataset(
        commodity=["a; b; c"],
        unit=["x; y"],
    )
    group = _group(
        [
            ("commodity", "#EXACT# a; b; c", "REPLACED", "unit", "#ANY#", "z")
        ]
    )
    result = _apply(dataset, group_rules=group)
    # Source: full-cell override.
    assert result.data.get_column("commodity").to_list() == ["REPLACED"]
    # Target: #ANY# adds 'z' to existing tokens.
    assert result.data.get_column("unit").to_list() == ["x; y; z"]


def test_normal_source_exact_target_still_works() -> None:
    """Normal source + #EXACT# in target: source token sub, target full-cell override."""
    dataset = _dataset(
        commodity=["a; b"],
        unit=["x; y; z"],
    )
    group = _group(
        [
            ("commodity", "a", "A", "unit", "#EXACT# x; y; z", "REPLACED")
        ]
    )
    result = _apply(dataset, group_rules=group)
    # Source: token substitution ('a' -> 'A', 'b' preserved).
    assert result.data.get_column("commodity").to_list() == ["A; b"]
    # Target: full-cell override.
    assert result.data.get_column("unit").to_list() == ["REPLACED"]


@pytest.mark.parametrize(
    "condition",
    ["#EXACT# a; b", " #EXACT# a; b", "  #exact#   a; b  ", "#Exact#a; b"],
)
def test_target_exact_directive_is_whitespace_and_case_tolerant(condition: str) -> None:
    """D2: the target ``#EXACT#`` marker tolerates surrounding whitespace and any case.

    ``resolve_exact_match_directive`` strips before testing the prefix, so a rule authored as
    ``  #Exact#   a; b  `` is equivalent to ``#EXACT# a; b``. The target rewrite must resolve
    the directive the same way ``match_target_condition_token_map`` does — an open-coded prefix
    test diverges on leading whitespace and silently turns the matched rule into a no-op.
    """
    dataset = _dataset(commodity=["src"], unit=["a; b"])
    group = _group([("commodity", "src", "src", "unit", condition, "X")], present=[True])
    result = _apply(dataset, group_rules=group)

    assert result.data.get_column("unit").to_list() == ["X"]
    assert result.changed_value_count == 1


def test_same_column_source_and_target_keeps_both_rewrites() -> None:
    """A rule group naming one column on both sides must not lose the source rewrite.

    The target rewrite reconstructs whole cells, so it has to tokenize the column as the
    source rewrite left it. Reading a snapshot taken before the source rewrite would scatter
    a cell rebuilt from stale tokens and silently discard the source-side substitution.
    """
    dataset = _dataset(commodity=["a; b"])
    group = _group([("commodity", "a", "A", "commodity", "b", "B")], present=[True])

    result = _apply(dataset, group_rules=group)

    # Source substitutes a -> A, target substitutes b -> B; both survive, canonicalized.
    assert result.data.get_column("commodity").to_list() == ["A; B"]
    assert result.changed_columns == ("commodity",)


@pytest.mark.parametrize("exact_first", [True, False])
def test_full_cell_override_outranks_token_rule_in_either_order(exact_first: bool) -> None:
    """D11: a full-cell override beats a token substitution regardless of rule order.

    D7's last-in-order precedence resolves collisions on the same token. An ``#EXACT#`` rule
    addresses the whole cell instead, so it never competes for a token slot and always wins.
    Pinned in both orders so the precedence cannot drift silently.
    """
    exact_rule: tuple[str | None, ...] = ("commodity", "src", "src", "unit", "#EXACT# a; b", "P")
    token_rule: tuple[str | None, ...] = ("commodity", "src", "src", "unit", "a", "Q")
    rules = [exact_rule, token_rule] if exact_first else [token_rule, exact_rule]

    dataset = _dataset(commodity=["src"], unit=["a; b"])
    result = _apply(dataset, group_rules=_group(rules, present=[True, True]))

    assert result.data.get_column("unit").to_list() == ["P"]


def test_distinct_source_and_target_columns_are_unaffected() -> None:
    """The same-column fix must be a no-op for the ordinary distinct-column case."""
    dataset = _dataset(commodity=["a; b"], unit=["x; y"])
    group = _group([("commodity", "a", "A", "unit", "x", "X")], present=[True])

    result = _apply(dataset, group_rules=group)

    assert result.data.get_column("commodity").to_list() == ["A; b"]
    assert result.data.get_column("unit").to_list() == ["X; y"]
