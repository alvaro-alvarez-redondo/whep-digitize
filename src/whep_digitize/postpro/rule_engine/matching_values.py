"""Target-condition matching, value merging, and change counting.

Three pure functions:

* :func:`match_rule_target_condition_values` — decide, element-wise, whether each rule
  target-condition value matches the current dataset value. For tokenized columns the current
  value is split on ``;`` and the condition matches by **token membership** (or a full-string
  match), with an explicit wildcard token (``__ANY__``). A null condition matches a null current
  value, and only that.
* :func:`concatenate_existing_and_incoming_values` — order-preserving, existing-first
  deduplicating merge of ``;``-delimited token sets (the ``concatenate`` strategy).
* :func:`count_elementwise_value_changes` — the element-wise change count that drives
  multi-pass convergence (early stop on zero change).

All keying goes through
:func:`whep_digitize.postpro.rule_engine.matching_strategy.encode_rule_match_key`, so match
correctness inherits the normalization policy (NFD diacritic strip + non-alphanumeric collapse).
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from whep_digitize.postpro.rule_engine.matching_strategy import encode_rule_match_key
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.assertions import require

_CONSTANTS = get_pipeline_constants()
_WILDCARD_TOKEN = _CONSTANTS.postpro.rule_match_wildcard_token
# R ``trimws()`` default whitespace class is ``[ \t\r\n]``; match it exactly.
_R_TRIMWS_CHARS = " \t\r\n"


def _encode_keys_list(values: Sequence[str | None], *, apply_normalization: bool) -> list[str]:
    """Encode a Python list of values to match keys via :func:`encode_rule_match_key`.

    Args:
        values: Values to key (``None`` folds to the NA match key).
        apply_normalization: Whether to normalize before keying.

    Returns:
        The list of match keys (no missing values).
    """
    if not values:
        return []
    series = pl.Series(values, dtype=pl.String)
    return encode_rule_match_key(series, apply_normalization=apply_normalization).to_list()


def _blank_to_none(value: str | None) -> str | None:
    """Return ``None`` for missing / whitespace-only values, else the value unchanged."""
    if value is None:
        return None
    return None if value.strip(_R_TRIMWS_CHARS) == "" else value


def _split_dedup_tokens(value: str) -> list[str]:
    """Split on ``;``, trim tokens, drop empties, and deduplicate (first occurrence wins).

    Args:
        value: A ``;``-delimited string.

    Returns:
        The ordered, deduplicated, non-empty tokens.
    """
    tokens = [token.strip(_R_TRIMWS_CHARS) for token in value.split(";")]
    non_empty = [token for token in tokens if token != ""]
    return list(dict.fromkeys(non_empty))


def match_rule_target_condition_values(
    current_values: pl.Series,
    condition_values: pl.Series,
    *,
    tokenized_target: bool = False,
    apply_match_normalization: bool = True,
    wildcard_token: str = _WILDCARD_TOKEN,
) -> pl.Series:
    """Match rule target-condition values against current dataset target values, element-wise.

    Non-tokenized columns compare full-string match keys. Tokenized columns split the current
    value on ``;`` and match the condition by **token membership** while still allowing a
    full-string match; the explicit ``wildcard_token`` matches anything, and an ``NA``
    condition matches only an ``NA`` current value.

    Args:
        current_values: Current dataset target values.
        condition_values: Rule target-condition values (same length as ``current_values``).
        tokenized_target: Enable tokenized (``;``-membership) matching.
        apply_match_normalization: Normalize match keys before comparison.
        wildcard_token: The explicit wildcard token (tokenized columns only).

    Returns:
        A Boolean Series of match decisions (same length as the inputs).

    Raises:
        ValidationError: If the inputs differ in length or ``wildcard_token`` is empty.
    """
    require(len(wildcard_token) >= 1, "wildcard_token must be a non-empty string")
    require(
        current_values.len() == condition_values.len(),
        "current and condition values must have equal length for condition matching",
    )
    if condition_values.len() == 0:
        return pl.Series([], dtype=pl.Boolean)

    if not tokenized_target:
        current_keys = encode_rule_match_key(
            current_values, apply_normalization=apply_match_normalization
        )
        condition_keys = encode_rule_match_key(
            condition_values, apply_normalization=apply_match_normalization
        )
        return (current_keys == condition_keys).rename("")

    length = condition_values.len()
    current_chr = current_values.cast(pl.String).to_list()
    condition_chr = condition_values.cast(pl.String).to_list()

    def _is_wildcard(condition: str | None) -> bool:
        return condition is not None and condition.strip(_R_TRIMWS_CHARS) == wildcard_token

    # NA condition -> matches an NA current value; wildcard -> always matches; else False so far.
    match_mask = [False] * length
    for index in range(length):
        condition = condition_chr[index]
        if condition is None:
            match_mask[index] = current_chr[index] is None
        elif _is_wildcard(condition):
            match_mask[index] = True

    non_na_idx = [
        index
        for index in range(length)
        if condition_chr[index] is not None and not _is_wildcard(condition_chr[index])
    ]
    if not non_na_idx:
        return pl.Series(match_mask, dtype=pl.Boolean)

    subset_condition_keys = _encode_keys_list(
        [condition_chr[index] for index in non_na_idx],
        apply_normalization=apply_match_normalization,
    )
    current_subset = [current_chr[index] for index in non_na_idx]

    # Per distinct current value: the set of token keys plus the full-string key.
    token_lookup: dict[str, set[str]] = {}
    for value in dict.fromkeys(item for item in current_subset if item is not None):
        token_keys = _encode_keys_list(
            _split_dedup_tokens(value), apply_normalization=apply_match_normalization
        )
        full_key = _encode_keys_list([value], apply_normalization=apply_match_normalization)[0]
        token_lookup[value] = {*token_keys, full_key}

    for position, out_index in enumerate(non_na_idx):
        current_value = current_subset[position]
        # An NA current value never matches. An empty-string current value also never matches:
        # R keys the token lookup by the current value, and base R cannot retrieve a list
        # element by an empty-string name (`list[[""]]` -> NULL, so `%in% NULL` is FALSE).
        # Reproduce both quirks so the tokenized match stays byte-identical to R.
        if current_value is None or current_value == "":
            match_mask[out_index] = False
            continue
        match_mask[out_index] = subset_condition_keys[position] in token_lookup[current_value]

    return pl.Series(match_mask, dtype=pl.Boolean)


def concatenate_existing_and_incoming_values(
    existing_values: pl.Series,
    incoming_values: pl.Series,
    delimiter: str,
) -> pl.Series:
    """Merge incoming values into existing values, preserving order and deduplicating tokens.

    Missing / blank values collapse to ``None``. When both sides are present, their
    ``;``-delimited token sets are concatenated existing-first and deduplicated (first
    occurrence wins); an existing-only or incoming-only value passes through unchanged.

    Args:
        existing_values: Current dataset values.
        incoming_values: Incoming update values (same length as ``existing_values``).
        delimiter: The token join delimiter.

    Returns:
        A string Series of merged values.

    Raises:
        ValidationError: If the inputs differ in length or ``delimiter`` is empty.
    """
    require(len(delimiter) >= 1, "delimiter must be a non-empty string")
    require(
        existing_values.len() == incoming_values.len(),
        "existing and incoming values must have equal length for concatenation",
    )
    existing_norm = [_blank_to_none(value) for value in existing_values.cast(pl.String).to_list()]
    incoming_norm = [_blank_to_none(value) for value in incoming_values.cast(pl.String).to_list()]

    merged: list[str | None] = []
    for existing, incoming in zip(existing_norm, incoming_norm, strict=True):
        if existing is not None and incoming is None:
            merged.append(existing)
        elif existing is not None and incoming is not None:
            tokens = list(
                dict.fromkeys(_split_dedup_tokens(existing) + _split_dedup_tokens(incoming))
            )
            merged.append(delimiter.join(tokens) if tokens else None)
        else:
            # Existing is missing: the merged value is the (possibly missing) incoming value.
            merged.append(incoming)

    return pl.Series(merged, dtype=pl.String)


def count_elementwise_value_changes(before_values: pl.Series, after_values: pl.Series) -> int:
    """Count element-wise value changes between two same-length Series.

    A position counts as changed when exactly one side is missing, or when both are present
    and differ. Two missing values are not a change. This count drives multi-pass convergence
    (a pass with zero changes is the early-stop signal).

    Args:
        before_values: Values before mutation.
        after_values: Values after mutation.

    Returns:
        The number of changed elements.

    Raises:
        ValidationError: If the inputs differ in length.
    """
    require(
        before_values.len() == after_values.len(),
        "before and after vectors must have equal length",
    )
    if before_values.len() == 0:
        return 0

    before = before_values.cast(pl.String)
    after = after_values.cast(pl.String)
    before_na = before.is_null()
    after_na = after.is_null()

    changed = (before_na != after_na) | ((~before_na) & (~after_na) & (before != after))
    return int(changed.sum())
