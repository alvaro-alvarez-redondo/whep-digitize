"""Target-condition matching, value merging, and change counting.

Three pure functions:

* :func:`match_rule_target_condition_values` — decide, element-wise, whether each rule
  target-condition value matches the current dataset value. For tokenized columns the current
  value is split on ``;`` and the condition matches by **token membership** (or a full-string
  match), with an explicit wildcard token (``#ANY#``). A null condition matches a null current
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
from whep_digitize.setup.helpers.strings import (
    resolve_exact_match_directive,
    split_token_cell,
)

_CONSTANTS = get_pipeline_constants()
_WILDCARD_TOKEN = _CONSTANTS.postpro.rule_match_wildcard_token
_EXACT_TOKEN = _CONSTANTS.postpro.rule_match_exact_token
# The whitespace class trimmed from values: space, tab, CR, LF.
_TRIM_CHARS = " \t\r\n"


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


def match_rule_target_condition_values(
    current_values: pl.Series,
    condition_values: pl.Series,
    *,
    apply_match_normalization: bool = True,
    wildcard_token: str = _WILDCARD_TOKEN,
    exact_token: str = _EXACT_TOKEN,
) -> pl.Series:
    """Match rule target-condition values against current dataset target values, element-wise.

    Matching is tokenized for **every** column: the current value is split on ``;`` and the
    condition matches on **token membership**, while a full-string match always also counts.
    The explicit ``wildcard_token`` matches anything, and an ``NA`` condition matches only an
    ``NA`` current value.

    Prefixing a condition with ``exact_token`` (``#EXACT#``) forces full-string matching for
    that rule: no token membership, and no wildcard interpretation — which is how a literal
    ``#ANY#`` is matched. See ``docs/pipeline-behaviors.md``.

    Args:
        current_values: Current dataset target values.
        condition_values: Rule target-condition values (same length as ``current_values``).
        apply_match_normalization: Normalize match keys before comparison.
        wildcard_token: The explicit wildcard token.
        exact_token: The exact-match directive marker.

    Returns:
        A Boolean Series of match decisions (same length as the inputs).

    Raises:
        ValidationError: If the inputs differ in length, or either token is empty.
    """
    require(len(wildcard_token) >= 1, "wildcard_token must be a non-empty string")
    require(len(exact_token) >= 1, "exact_token must be a non-empty string")
    require(
        current_values.len() == condition_values.len(),
        "current and condition values must have equal length for condition matching",
    )
    if condition_values.len() == 0:
        return pl.Series([], dtype=pl.Boolean)

    current_chr = current_values.cast(pl.String).to_list()
    raw_condition_chr = condition_values.cast(pl.String).to_list()
    resolved = [resolve_exact_match_directive(value, exact_token) for value in raw_condition_chr]
    condition_chr = [value for value, _ in resolved]
    exact_flags = [is_exact for _, is_exact in resolved]

    # Full-string equality, vectorized. For a current value with no ``;`` this is already the
    # whole answer: its token set is just itself, so membership reduces to equality. Only rows
    # whose current value is multi-token need the per-row set lookup below.
    current_keys = encode_rule_match_key(
        current_values, apply_normalization=apply_match_normalization
    )
    condition_keys = encode_rule_match_key(
        pl.Series(condition_chr, dtype=pl.String), apply_normalization=apply_match_normalization
    )
    full_match = (current_keys == condition_keys).to_list()
    condition_key_list = condition_keys.to_list()

    def _is_wildcard(index: int) -> bool:
        condition = condition_chr[index]
        return (
            not exact_flags[index]
            and condition is not None
            # Case-insensitive for the same reason as the exact marker: rule files are typed by
            # hand, and a case slip would silently turn the wildcard into a literal.
            and condition.strip(_TRIM_CHARS).casefold() == wildcard_token.casefold()
        )

    # A null current value matches only a null condition. An empty-string current value never
    # matches under tokenized matching -- the token lookup cannot key it -- but it does match an
    # empty condition under ``#EXACT#``, which is pure full-string equality. Both are
    # intentional; see docs/pipeline-behaviors.md.
    match_mask = [
        _is_wildcard(index)
        or (
            current_chr[index] is not None
            and (exact_flags[index] or current_chr[index] != "")
            and bool(full_match[index])
        )
        or (current_chr[index] is None and condition_chr[index] is None)
        for index in range(condition_values.len())
    ]

    pending = [
        index
        for index in range(condition_values.len())
        if not match_mask[index]
        and not exact_flags[index]
        and current_chr[index] is not None
        and ";" in current_chr[index]
    ]
    if not pending:
        return pl.Series(match_mask, dtype=pl.Boolean)

    # Token keys per distinct multi-token current value (the full-string key already matched
    # above, so only the split tokens are needed here).
    token_lookup: dict[str, set[str]] = {}
    for value in dict.fromkeys(current_chr[index] for index in pending):
        assert value is not None  # `pending` only holds indexes with a non-null current value
        token_lookup[value] = set(
            _encode_keys_list(
                split_token_cell(value), apply_normalization=apply_match_normalization
            )
        )

    for index in pending:
        current_value = current_chr[index]
        assert current_value is not None
        match_mask[index] = condition_key_list[index] in token_lookup[current_value]

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
    merged: list[str | None] = []
    for existing, incoming in zip(
        existing_values.cast(pl.String).to_list(),
        incoming_values.cast(pl.String).to_list(),
        strict=True,
    ):
        tokens = sorted(set(split_token_cell(existing)) | set(split_token_cell(incoming)))
        merged.append(delimiter.join(tokens) if tokens else None)

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
