"""Unit tests for the postpro rule-engine matching strategy and value merge.

Ports of ``23-matching-strategy.R`` (:mod:`whep_digitize.postpro.rule_engine.matching_strategy`)
and ``23-matching-values.R`` (:mod:`whep_digitize.postpro.rule_engine.matching_values`). Byte
parity vs R is covered separately in ``tests/parity/test_matching_parity.py``; these tests pin
the behavioral contract (NA handling, tokenized membership, wildcard, existing-first dedupe,
change counting, strategy resolution) without needing R.
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
    resolve_tokenized_target_condition_columns,
)
from whep_digitize.postpro.rule_engine.matching_values import (
    concatenate_existing_and_incoming_values,
    count_elementwise_value_changes,
    match_rule_target_condition_values,
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
    result = match_rule_target_condition_values(current, condition, tokenized_target=True)
    assert result.to_list() == [True, True, False]
    assert result.dtype == pl.Boolean


def test_match_tokenized_wildcard_matches_anything_including_null_current() -> None:
    current = _s(["anything", None])
    condition = _s(["__ANY__", "__ANY__"])
    result = match_rule_target_condition_values(current, condition, tokenized_target=True)
    assert result.to_list() == [True, True]


def test_match_tokenized_na_matches_only_na() -> None:
    current = _s([None, "a", None])
    condition = _s([None, None, "a"])
    result = match_rule_target_condition_values(current, condition, tokenized_target=True)
    # NA<->NA True; NA-condition vs present current False; present-condition vs NA current False.
    assert result.to_list() == [True, False, False]


def test_match_tokenized_empty_string_current_never_matches() -> None:
    # R keys the token lookup by the current value and cannot retrieve an empty-string name
    # (`list[[""]]` -> NULL); the port reproduces that quirk.
    result = match_rule_target_condition_values(_s([""]), _s([""]), tokenized_target=True)
    assert result.to_list() == [False]


def test_match_tokenized_ignores_blank_and_internal_empty_tokens() -> None:
    result = match_rule_target_condition_values(_s(["a; ; b"]), _s(["b"]), tokenized_target=True)
    assert result.to_list() == [True]


def test_match_tokenized_custom_wildcard_token() -> None:
    result = match_rule_target_condition_values(
        _s(["x"]), _s(["*"]), tokenized_target=True, wildcard_token="*"
    )
    assert result.to_list() == [True]


# --------------------------------------------------------------------------- plain matching


def test_match_plain_compares_normalized_full_string() -> None:
    current = _s(["Café", "a; b; c", "a; b"])
    condition = _s(["cafe", "a; b; c", "b; a"])
    result = match_rule_target_condition_values(current, condition, tokenized_target=False)
    # accents normalize equal; full string equal; reordered tokens differ.
    assert result.to_list() == [True, True, False]


def test_match_plain_na_matches_na() -> None:
    result = match_rule_target_condition_values(_s([None, None]), _s([None, "a"]))
    assert result.to_list() == [True, False]


def test_match_plain_wildcard_is_literal() -> None:
    # Outside tokenized mode the wildcard token has no special meaning.
    result = match_rule_target_condition_values(_s(["x"]), _s(["__ANY__"]))
    assert result.to_list() == [False]


def test_match_empty_inputs_return_empty_boolean_series() -> None:
    result = match_rule_target_condition_values(_s([]), _s([]), tokenized_target=True)
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


def test_concatenate_existing_only_passes_through_raw_without_dedupe() -> None:
    # existing-only values are NOT token-deduplicated (only the both-present branch dedupes).
    result = concatenate_existing_and_incoming_values(_s(["p; p; q"]), _s([None]), "; ")
    assert result.to_list() == ["p; p; q"]


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


def test_resolve_tokenized_target_condition_columns_sorted_unique() -> None:
    assert resolve_tokenized_target_condition_columns() == ("footnotes", "notes")


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
