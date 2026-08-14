"""String normalization — the pipeline's canonical text-folding policy.

Implements the normalization **policy** directly: fold text to lowercase ASCII, replace runs of
characters that are neither alphanumeric nor **retained punctuation** with a single space, then
squish and trim. The retained punctuation is ``; , : ( ) [ ]`` — the same set for every column,
footnotes included. Match-key normalization uses the same policy, so it decides whether
post-processing rules fire.

The "fold to ASCII" step is a principled Unicode diacritic strip: NFD decomposition, then drop
the combining marks. No historical or compatibility expansions are applied — a symbol such as
``®``, ``½`` or ``±`` carries no ASCII base, so it is removed by the replacement step
rather than expanded (``Philippines®`` -> ``philippines``, ``½ kg`` -> ``kg``), and
super/subscripts and ligatures are likewise never unpacked. Accented Latin letters fold to
their base (``café`` -> ``cafe``, ``ñ`` -> ``n``); letters with no canonical decomposition
(``ø``, ``ß``, ``æ``, ligatures) are treated like any other non-retained character and
dropped (``straße`` -> ``stra e``). There are no character-specific exceptions.
"""

from __future__ import annotations

import re
import unicodedata

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants

_constants = get_pipeline_constants()
_NORMALIZE_NON_ALNUM = re.compile(_constants.patterns.normalize_non_alnum)
_UNKNOWN_FILENAME = _constants.defaults.unknown_filename
_TOKEN_DELIMITER = _constants.postpro.target_update_strategies.concatenate_delimiter
_EXACT_MATCH_TOKEN = _constants.postpro.rule_match_exact_token
# The whitespace class used for token trimming: space, tab, CR, LF only -- deliberately
# not the full Unicode whitespace set.
_TRIM_CHARS = " \t\r\n"


def transliterate_ascii_lower(text: str) -> str:
    """Fold to lowercase ASCII by stripping diacritics, then lowercase.

    The single implementation of the pipeline's transliteration, shared by match-key
    normalization (:func:`normalize_text`) and header normalization
    (:mod:`whep_digitize.ingest.reading.header_normalization`) so both fold identically.

    Implements the policy step directly: decompose to NFD and drop the combining marks, so an
    accented Latin letter folds to its base (``é`` -> ``e``, ``ñ`` -> ``n``), then lowercase.
    There are deliberately no symbol expansions (``®``, ``½``, ``±``), no compatibility folds
    (superscripts, ligatures, ``ß`` -> ``ss``), and no character-specific exceptions. Any
    codepoint without a canonical ASCII base is left unchanged here and removed by the caller's
    non-alphanumeric step. Pure-ASCII text takes the lowercase fast path.

    Args:
        text: The value to fold.

    Returns:
        The diacritic-folded, lowercased string. It may retain non-ASCII codepoints (symbols,
        non-Latin scripts, non-decomposable letters); the caller's non-alphanumeric replacement
        drops them.
    """
    if text.isascii():
        return text.lower()
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def normalize_text(text: str | None) -> str | None:
    """Normalize a single string to lowercase ASCII alphanumerics, retained punctuation + spaces.

    Transliterate -> lowercase -> replace runs of characters that are neither alphanumeric nor
    retained punctuation with a single space -> strip. The retained punctuation is
    ``; , : ( ) [ ]``; everything else (``.``, ``/``, ``*``, ``-``, ``#``, ``%``, ``'``, ...) is
    replaced. ``None`` passes through unchanged as ``None``.

    Args:
        text: The value to normalize.

    Returns:
        The normalized string, or ``None`` if the input was ``None``.
    """
    if text is None:
        return None
    collapsed = _NORMALIZE_NON_ALNUM.sub(" ", transliterate_ascii_lower(text))
    return collapsed.strip()


def normalize_string(values: pl.Series) -> pl.Series:
    """Normalize a whole column via the cardinality fast path.

    Distinct values are normalized once in Python and mapped back, so the cost scales with
    cardinality rather than row count. Nulls are preserved.

    Args:
        values: A string :class:`polars.Series`.

    Returns:
        A normalized string :class:`polars.Series` of the same length.
    """
    uniques = values.drop_nulls().unique().to_list()
    mapping = {value: normalize_text(value) for value in uniques}
    return values.replace_strict(mapping, default=None, return_dtype=pl.String)


def resolve_exact_match_directive(
    condition: str | None, exact_token: str = _EXACT_MATCH_TOKEN
) -> tuple[str | None, bool]:
    """Split the exact-match directive off a rule target-condition value.

    A condition value prefixed with ``exact_token`` (default ``#EXACT#``) opts that rule out of
    ``;``-token membership and out of wildcard interpretation, so it matches the full string
    only. The marker is a rule-authoring directive, not data, so it is stripped before keying.

    Rule files are hand-authored, so the marker is matched **case-insensitively** and any
    whitespace around it is ignored: ``#EXACT#africa``, ``#exact# africa`` and
    ``  #Exact#   africa  `` are equivalent. Getting the case wrong would otherwise leave the
    marker in the value and silently stop the rule from ever matching.

    Args:
        condition: The raw target-condition value.
        exact_token: The directive marker.

    Returns:
        ``(condition_without_marker, is_exact)``. Untouched values return ``(condition, False)``.
    """
    if condition is None:
        return None, False
    stripped = condition.strip(_TRIM_CHARS)
    if stripped[: len(exact_token)].casefold() != exact_token.casefold():
        return condition, False
    return stripped[len(exact_token) :].strip(_TRIM_CHARS), True


def split_token_cell(value: str | None) -> list[str]:
    """Split one ``;``-delimited cell into its canonical tokens.

    **The pipeline's single token-splitting implementation.** Tokens are trimmed, empties are
    dropped, duplicates are removed, and the result is sorted by Unicode code point (equivalently
    UTF-8 byte order, so it is locale-independent). Splitting is strictly **within one cell** —
    tokens are never mixed, shared, or reordered across cells, rows, or columns.

    A null cell, or one holding nothing but separators and whitespace, has no tokens.

    Args:
        value: The raw cell value.

    Returns:
        The canonical token list (empty when the cell holds no non-empty token).
    """
    if value is None:
        return []
    tokens = (token.strip(_TRIM_CHARS) for token in value.split(";"))
    return sorted({token for token in tokens if token})


def canonicalize_token_cell(value: str | None, delimiter: str = _TOKEN_DELIMITER) -> str | None:
    """Canonicalize one ``;``-delimited cell: split, trim, drop empties, dedupe, sort, rejoin.

    This is the pipeline's single canonical token form, applied **strictly within one cell** —
    tokens are never mixed, shared, or reordered across cells, rows, or columns. Sorting is by
    Unicode code point (equivalently UTF-8 byte order), so it is locale-independent.

    A cell of nothing but separators and whitespace is missing data, not an empty string, so it
    canonicalizes to ``None``.

    Args:
        value: The raw cell value.
        delimiter: The output token delimiter.

    Returns:
        The canonical cell, or ``None`` when the cell holds no non-empty token.
    """
    tokens = split_token_cell(value)
    return delimiter.join(tokens) if tokens else None


def canonicalize_token_column(values: pl.Series, delimiter: str = _TOKEN_DELIMITER) -> pl.Series:
    """Apply :func:`canonicalize_token_cell` across a column via the cardinality fast path.

    Args:
        values: The cell values (any dtype; cast to string).
        delimiter: The output token delimiter.

    Returns:
        A ``String`` Series of canonical cells, carrying the input's name.
    """
    string_values = values.cast(pl.String)
    mapping = {
        value: canonicalize_token_cell(value, delimiter)
        for value in string_values.drop_nulls().unique().to_list()
    }
    if not mapping:
        return string_values
    return string_values.replace_strict(mapping, default=None, return_dtype=pl.String)


def normalize_filename(filename: str | None) -> str:
    """Normalize a name for use as a file stem (spaces become underscores).

    Empty or ``None`` input yields the ``unknown`` placeholder.

    Args:
        filename: The name to normalize.

    Returns:
        A filesystem-safe, normalized name.
    """
    normalized = normalize_text(filename)
    if not normalized:
        return _UNKNOWN_FILENAME
    return normalized.replace(" ", "_")
