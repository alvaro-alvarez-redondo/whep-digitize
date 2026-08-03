r"""Postpro / clean_harmonize — stage input/output canonicalization.

After the multi-pass loop finishes, canonicalize the ``;``-delimited annotation columns
(``notes`` / ``footnotes``) — split, trim, drop empties, dedupe, and code-point-sort each cell's
tokens — and drop the ``footnotes`` column when it ends up entirely missing (and was already
all-missing on input).

Every helper here is pure: the input frame is never mutated, a new frame is returned.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants

_CONSTANTS = get_pipeline_constants()
_CONCAT_DELIMITER = _CONSTANTS.postpro.target_update_strategies.concatenate_delimiter
# The whitespace class used for token trimming: space, tab, CR, LF only — deliberately not the
# full Unicode whitespace set.
_R_TRIMWS_CHARS = " \t\r\n"
_ANNOTATION_COLUMNS = ("notes", "footnotes")
_FOOTNOTES_COLUMN = "footnotes"


def _canonicalize_cell(value: str, delimiter: str) -> str | None:
    """Split one cell on ``;``, trim + drop empty tokens, dedupe, sort by code point, rejoin.

    Returns ``None`` when the cell is blank or contains no non-empty tokens — a cell of nothing
    but separators and whitespace is missing data, not an empty string. Deduplication keeps first
    appearance and the result is then code-point sorted, which is equivalently just a code-point
    sort of the distinct tokens (UTF-8 byte order equals code-point order).
    """
    if value.strip(_R_TRIMWS_CHARS) == "":
        return None
    tokens = [token.strip(_R_TRIMWS_CHARS) for token in value.split(";")]
    non_empty = [token for token in tokens if token]
    if not non_empty:
        return None
    return delimiter.join(sorted(dict.fromkeys(non_empty)))


def canonicalize_semicolon_delimited_cells(
    values: pl.Series, delimiter: str = _CONCAT_DELIMITER
) -> pl.Series:
    """Canonicalize each ``;``-delimited cell of a Series (dedupe + code-point-sort tokens).

    Missing / blank cells map to ``None``, and nulls pass through as ``None``. The scalar-Python
    canonicalization is computed once per *distinct* value and mapped back vectorized
    (``unique()`` + ``replace_strict``), avoiding a Python loop over every row — these annotation
    columns are low-cardinality, so the distinct set is small.

    Args:
        values: The cell values (any dtype; cast to string).
        delimiter: The output token delimiter.

    Returns:
        A ``String`` Series of canonicalized values, carrying the input's name.
    """
    string_values = values.cast(pl.String)
    mapping = {
        value: _canonicalize_cell(value, delimiter)
        for value in string_values.drop_nulls().unique().to_list()
    }
    if not mapping:
        return string_values
    return string_values.replace_strict(mapping, default=None, return_dtype=pl.String)


def canonicalize_post_loop_annotation_columns(dataset: pl.DataFrame) -> pl.DataFrame:
    """Canonicalize the ``notes`` / ``footnotes`` columns that are present.

    Args:
        dataset: The stage dataset (not mutated).

    Returns:
        A new frame with each present annotation column canonicalized (unchanged if neither
        column is present).
    """
    present = [column for column in _ANNOTATION_COLUMNS if column in dataset.columns]
    if not present:
        return dataset
    return dataset.with_columns(
        canonicalize_semicolon_delimited_cells(dataset.get_column(column), _CONCAT_DELIMITER)
        for column in present
    )


def drop_empty_footnotes_column(dataset: pl.DataFrame) -> pl.DataFrame:
    """Drop ``footnotes`` when every value is missing.

    Args:
        dataset: The stage dataset (not mutated).

    Returns:
        A new frame without ``footnotes`` when that column is present and all-null; otherwise the
        frame unchanged.
    """
    if _FOOTNOTES_COLUMN not in dataset.columns:
        return dataset
    if dataset.get_column(_FOOTNOTES_COLUMN).null_count() == dataset.height:
        return dataset.drop(_FOOTNOTES_COLUMN)
    return dataset
