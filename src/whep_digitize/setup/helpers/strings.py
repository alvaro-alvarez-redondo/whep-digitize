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
_FOOTNOTE_NON_ALNUM = re.compile(_constants.patterns.footnote_non_alnum)
_UNKNOWN_FILENAME = _constants.defaults.unknown_filename


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


def clean_footnote(text: str | None) -> str | None:
    """Normalize a footnote, retaining the punctuation set ``; , : ( ) [ ]``.

    Behaviourally identical to :func:`normalize_text`: the two share one retained-punctuation
    set and both collapse every run of other characters to a single space. Kept as a separate
    entry point because footnotes are the tokenized column and may diverge again later.

    Args:
        text: The footnote value to clean.

    Returns:
        The cleaned footnote, or ``None`` if the input was ``None``.
    """
    if text is None:
        return None
    cleaned = _FOOTNOTE_NON_ALNUM.sub(" ", transliterate_ascii_lower(text))
    return cleaned.strip()


def clean_footnote_column(values: pl.Series) -> pl.Series:
    """Apply :func:`clean_footnote` across a column via the cardinality fast path.

    Args:
        values: A string :class:`polars.Series` of footnotes.

    Returns:
        A cleaned string :class:`polars.Series` of the same length.
    """
    uniques = values.drop_nulls().unique().to_list()
    mapping = {value: clean_footnote(value) for value in uniques}
    return values.replace_strict(mapping, default=None, return_dtype=pl.String)


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
