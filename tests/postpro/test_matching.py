"""Unit tests for the postpro rule-engine matching strategy and value merge.

Covers :mod:`whep_digitize.postpro.rule_engine.matching_strategy`
and :mod:`whep_digitize.postpro.rule_engine.matching_values`. Byte
parity is covered separately in ``tests/parity/test_matching_parity.py``; these tests pin
the behavioral contract (NA handling, tokenized membership, wildcard, existing-first dedupe,
change counting, strategy resolution).
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.rule_engine.matching_strategy import (
    TargetUpdateStrategyConfig,
    decode_target_rule_value,
    empty_last_rule_wins_overwrite_events_df,
    encode_rule_match_key,
    encode_target_rule_value,
    get_target_update_strategy_config,
    resolve_last_rule_wins_unique_row_fast_path_enabled,
    resolve_rule_match_normalization_settings,
    resolve_target_update_strategy,
)
from whep_digitize.postpro.rule_engine.matching_values import (
    concatenate_existing_and_incoming_values,
    count_elementwise_value_changes,
    match_rule_target_condition_values,
    resolve_exact_match_directive,
)
from whep_digitize.setup.errors import ConfigurationError, ValidationError

_NA_MATCH_KEY = "..NA_MATCH_KEY.."
_NA_PLACEHOLDER = "..NA_INTERNAL.."


def _s(values: list[str | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


# --------------------------------------------------------------------------- encode / decode


def test_encode_target_rule_value_folds_missing_and_blank() -> None:
    result = encode_target_rule_value(_s(["a", None, "", "  ", "keep"]))
    assert result.to_list() == ["a", _NA_PLACEHOLDER, _NA_PLACEHOLDER, _NA_PLACEHOLDER, "keep"]


def test_encode_target_rule_value_empty_series() -> None:
    result = encode_target_rule_value(_s([]))
    assert result.to_list() == []
    assert result.dtype == pl.String


def test_encode_target_rule_value_custom_placeholder() -> None:
    result = encode_target_rule_value(_s([None, "x"]), na_placeholder="<NA>")
    assert result.to_list() == ["<NA>", "x"]


def test_encode_target_rule_value_rejects_empty_placeholder() -> None:
    with pytest.raises(ValidationError):
        encode_target_rule_value(_s(["a"]), na_placeholder="")


def test_decode_target_rule_value_reverts_placeholder_only() -> None:
    encoded = _s([_NA_PLACEHOLDER, "a", None, "keep"])
    assert decode_target_rule_value(encoded).to_list() == [None, "a", None, "keep"]


def test_encode_decode_round_trip_maps_literal_placeholder_to_null() -> None:
    original = _s(["a", None, "", _NA_PLACEHOLDER])
    round_tripped = decode_target_rule_value(encode_target_rule_value(original))
    # None/blank encode to the placeholder then decode to None; a pre-existing literal
    # placeholder also decodes to None.
    assert round_tripped.to_list() == ["a", None, None, None]


# --------------------------------------------------------------------------- match keys


def test_encode_rule_match_key_normalizes_and_folds_na() -> None:
    result = encode_rule_match_key(_s(["Café", None, "  A  B  "]))
    assert result.to_list() == ["cafe", _NA_MATCH_KEY, "a b"]


def test_encode_rule_match_key_raw_keeps_value_but_folds_na() -> None:
    result = encode_rule_match_key(_s(["Café", None]), apply_normalization=False)
    assert result.to_list() == ["Café", _NA_MATCH_KEY]


def test_encode_rule_match_key_empty_series() -> None:
    assert encode_rule_match_key(_s([])).to_list() == []


# --------------------------------------------------------------------------- tokenized matching


def test_match_tokenized_token_membership_and_full_string() -> None:
    current = _s(["a; b; c", "a; b; c", "a; b"])
    condition = _s(["b", "a; b; c", "b; a"])
    # token "b" matches; the full-string key "a b c" matches; reordered "b a" does not.
    result = match_rule_target_condition_values(current, condition)
    assert result.to_list() == [True, True, False]
    assert result.dtype == pl.Boolean


def test_match_tokenized_wildcard_matches_anything_including_null_current() -> None:
    current = _s(["anything", None])
    condition = _s(["#ANY#", "#ANY#"])
    result = match_rule_target_condition_values(current, condition)
    assert result.to_list() == [True, True]


def test_match_tokenized_na_matches_only_na() -> None:
    current = _s([None, "a", None])
    condition = _s([None, None, "a"])
    result = match_rule_target_condition_values(current, condition)
    # NA<->NA True; NA-condition vs present current False; present-condition vs NA current False.
    assert result.to_list() == [True, False, False]


def test_match_tokenized_empty_string_current_never_matches() -> None:
    # The token lookup is keyed by the current value and treats the empty key as absent
    # (`list[[""]]` -> NULL); the port reproduces that quirk.
    result = match_rule_target_condition_values(_s([""]), _s([""]))
    assert result.to_list() == [False]


def test_match_tokenized_ignores_blank_and_internal_empty_tokens() -> None:
    result = match_rule_target_condition_values(_s(["a; ; b"]), _s(["b"]))
    assert result.to_list() == [True]


def test_match_tokenized_custom_wildcard_token() -> None:
    result = match_rule_target_condition_values(_s(["x"]), _s(["*"]), wildcard_token="*")
    assert result.to_list() == [True]


# ------------------------------------------------------- exact-match directive (#EXACT#)


def test_match_compares_normalized_full_string() -> None:
    current = _s(["Café", "a; b; c", "a; b"])
    condition = _s(["cafe", "a; b; c", "b; a"])
    result = match_rule_target_condition_values(current, condition)
    # accents normalize equal; full string equal; reordered tokens differ.
    assert result.to_list() == [True, True, False]


def test_tokenization_applies_to_every_column() -> None:
    # A single token matches a multi-token current value -- no per-column opt-in any more.
    current = _s(["africa; america; asia", "north; south", "spain"])
    condition = _s(["africa", "south", "spain"])
    assert match_rule_target_condition_values(current, condition).to_list() == [True, True, True]


def test_exact_directive_suppresses_token_membership() -> None:
    current = _s(["africa; america", "africa; america"])
    condition = _s(["africa", "#EXACT#africa"])
    # Without the directive a token matches; with it, only the full string would.
    assert match_rule_target_condition_values(current, condition).to_list() == [True, False]


def test_exact_directive_still_matches_the_full_string() -> None:
    current = _s(["africa; america"])
    condition = _s(["#EXACT#africa; america"])
    assert match_rule_target_condition_values(current, condition).to_list() == [True]


def test_exact_directive_makes_the_wildcard_literal() -> None:
    current = _s(["#ANY#", "anything"])
    condition = _s(["#EXACT##ANY#", "#EXACT##ANY#"])
    # The directive opts out of wildcard interpretation, so #ANY# is matched literally.
    assert match_rule_target_condition_values(current, condition).to_list() == [True, False]


def test_resolve_exact_match_directive_strips_marker_and_flags() -> None:
    assert resolve_exact_match_directive("#EXACT#africa") == ("africa", True)
    assert resolve_exact_match_directive("  #EXACT# africa ") == ("africa", True)
    assert resolve_exact_match_directive("africa") == ("africa", False)
    assert resolve_exact_match_directive(None) == (None, False)


@pytest.mark.parametrize(
    "condition",
    [
        "#EXACT#africa; america",
        "#EXACT# africa; america",  # a space after the marker reads better in a rule file
        "#EXACT#   africa; america",
        "  #EXACT# africa; america  ",
        "#exact# africa; america",  # hand-authored rule files must not depend on case
        "#Exact#africa; america",
    ],
)
def test_exact_directive_ignores_case_and_surrounding_whitespace(condition: str) -> None:
    result = match_rule_target_condition_values(_s(["africa; america"]), _s([condition]))
    assert result.to_list() == [True]


@pytest.mark.parametrize("wildcard", ["#ANY#", "#any#", "#Any#", "  #ANY#  "])
def test_wildcard_ignores_case_and_surrounding_whitespace(wildcard: str) -> None:
    assert match_rule_target_condition_values(_s(["anything"]), _s([wildcard])).to_list() == [True]


def test_match_plain_na_matches_na() -> None:
    result = match_rule_target_condition_values(_s([None, None]), _s([None, "a"]))
    assert result.to_list() == [True, False]


def test_wildcard_now_applies_to_every_column() -> None:
    # Tokenized matching is unconditional, so the wildcard is honoured everywhere. Use the
    # #EXACT# directive (covered above) when a literal "#ANY#" is wanted instead.
    result = match_rule_target_condition_values(_s(["x"]), _s(["#ANY#"]))
    assert result.to_list() == [True]


def test_match_empty_inputs_return_empty_boolean_series() -> None:
    result = match_rule_target_condition_values(_s([]), _s([]))
    assert result.to_list() == []
    assert result.dtype == pl.Boolean


def test_match_length_mismatch_raises() -> None:
    with pytest.raises(ValidationError):
        match_rule_target_condition_values(_s(["a"]), _s(["a", "b"]))


def test_match_rejects_empty_wildcard_token() -> None:
    with pytest.raises(ValidationError):
        match_rule_target_condition_values(_s(["a"]), _s(["a"]), wildcard_token="")


# --------------------------------------------------------------------------- concatenate merge


def test_concatenate_merges_existing_first_and_dedupes() -> None:
    result = concatenate_existing_and_incoming_values(_s(["a; b"]), _s(["b; c"]), "; ")
    assert result.to_list() == ["a; b; c"]


def test_concatenate_canonicalizes_an_existing_only_value() -> None:
    # Every reconstruction path is canonical now: an existing-only value is deduped and sorted
    # too, not passed through raw.
    result = concatenate_existing_and_incoming_values(_s(["q; p; p"]), _s([None]), "; ")
    assert result.to_list() == ["p; q"]


def test_concatenate_both_present_dedupes_existing_tokens() -> None:
    result = concatenate_existing_and_incoming_values(_s(["a; a; b"]), _s(["c"]), "; ")
    assert result.to_list() == ["a; b; c"]


def test_concatenate_missing_and_blank_semantics() -> None:
    existing = _s([None, "y", None, "", ";"])
    incoming = _s(["x", None, None, "z", ";"])
    result = concatenate_existing_and_incoming_values(existing, incoming, "; ")
    # incoming-only -> incoming; existing-only -> existing; both missing -> None;
    # blank existing -> incoming; both all-empty tokens -> None.
    assert result.to_list() == ["x", "y", None, "z", None]


def test_concatenate_trims_tokens() -> None:
    result = concatenate_existing_and_incoming_values(_s(["a ; b"]), _s([" b ;c "]), "; ")
    assert result.to_list() == ["a; b; c"]


def test_concatenate_length_mismatch_raises() -> None:
    with pytest.raises(ValidationError):
        concatenate_existing_and_incoming_values(_s(["a"]), _s(["a", "b"]), "; ")


def test_concatenate_rejects_empty_delimiter() -> None:
    with pytest.raises(ValidationError):
        concatenate_existing_and_incoming_values(_s(["a"]), _s(["b"]), "")


# --------------------------------------------------------------------------- change counting


def test_count_elementwise_value_changes_counts_na_transitions_and_diffs() -> None:
    before = _s(["a", "b", None, "c", None, "d"])
    after = _s(["a", "x", None, None, "y", "d"])
    # unchanged, changed, both-NA (no), present->NA (yes), NA->present (yes), unchanged.
    assert count_elementwise_value_changes(before, after) == 3


def test_count_elementwise_value_changes_empty() -> None:
    assert count_elementwise_value_changes(_s([]), _s([])) == 0


def test_count_elementwise_value_changes_length_mismatch_raises() -> None:
    with pytest.raises(ValidationError):
        count_elementwise_value_changes(_s(["a"]), _s(["a", "b"]))


# --------------------------------------------------------------------------- strategy config


def test_resolve_rule_match_normalization_settings() -> None:
    settings = resolve_rule_match_normalization_settings()
    assert settings.apply_once_before_stage is True
    assert settings.apply_each_pass is False
    assert settings.excluded_columns == ("year", "value", "yearbook", "document")


def test_get_target_update_strategy_config() -> None:
    config = get_target_update_strategy_config()
    assert config.default == "last_rule_wins"
    assert config.supported == ("last_rule_wins", "concatenate")
    assert config.concatenate_delimiter == "; "
    assert config.by_column == {"notes": "concatenate"}


def test_resolve_target_update_strategy_uses_override_then_default() -> None:
    assert resolve_target_update_strategy("notes") == "concatenate"
    assert resolve_target_update_strategy("unit") == "last_rule_wins"


def test_resolve_target_update_strategy_rejects_empty_column() -> None:
    with pytest.raises(ValidationError):
        resolve_target_update_strategy("")


def test_resolve_target_update_strategy_rejects_unsupported_strategy() -> None:
    bad_config = TargetUpdateStrategyConfig(
        default="last_rule_wins",
        supported=("last_rule_wins", "concatenate"),
        concatenate_delimiter="; ",
        by_column={"weird": "unsupported_strategy"},
    )
    with pytest.raises(ConfigurationError):
        resolve_target_update_strategy("weird", bad_config)


def test_resolve_last_rule_wins_unique_row_fast_path_enabled() -> None:
    assert resolve_last_rule_wins_unique_row_fast_path_enabled() is True


def test_empty_last_rule_wins_overwrite_events_df_schema() -> None:
    frame = empty_last_rule_wins_overwrite_events_df()
    assert frame.height == 0
    assert frame.columns == [
        "dataset_name",
        "execution_stage",
        "rule_file_identifier",
        "column_source",
        "column_target",
        "row_id",
        "candidate_count",
        "unique_candidate_count",
        "selected_value",
        "candidate_values",
    ]
    assert frame.schema["row_id"] == pl.Int64
