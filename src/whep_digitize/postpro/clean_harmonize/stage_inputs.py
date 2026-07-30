r"""Postpro / clean_harmonize — stage input/output canonicalization.

The Python port of ``r/2-postpro_pipeline/22-clean_harmonize_data/22-stage-inputs.R``: after the
multi-pass loop finishes, canonicalize the ``;``-delimited annotation columns (``notes`` /
``footnotes``) — split, trim, drop empties, dedupe, and radix-sort each cell's tokens — and drop
the ``footnotes`` column when it ends up entirely missing (but was already all-missing on input).

R mutated the ``data.table`` by reference; this port is functional and returns a new frame.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants

_CONSTANTS = get_pipeline_constants()
_CONCAT_DELIMITER = _CONSTANTS.postpro.target_update_strategies.concatenate_delimiter
# R ``trimws()`` default whitespace class is ``[ \t\r\n]``; match it exactly.
_R_TRIMWS_CHARS = " \t\r\n"
_ANNOTATION_COLUMNS = ("notes", "footnotes")
_FOOTNOTES_COLUMN = "footnotes"


def _canonicalize_cell(value: str, delimiter: str) -> str | None:
    """Split one cell on ``;``, trim + drop empty tokens, dedupe, radix-sort, rejoin.

    Returns ``None`` when the cell is blank or contains no non-empty tokens (R sets such cells to
    ``NA``). Deduplication is first-appearance then radix (code-point) sort — equivalently just a
    code-point sort of the distinct tokens (UTF-8 byte order equals code-point order).
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
    """Canonicalize each ``;``-delimited cell of a Series (dedupe + radix-sort tokens).

    The Python port of R ``canonicalize_semicolon_delimited_cells``. Missing / blank cells map to
    ``None``. The scalar-Python canonicalization is computed once per *distinct* value and mapped
    back vectorized (``unique()`` + ``replace_strict``) — the polars-idiomatic form of R's memoized
    implementation, avoiding a Python loop over every row (these annotation columns are
    low-cardinality). Nulls pass through as ``None``.

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

    The Python port of R ``canonicalize_post_loop_annotation_columns``.

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

    The Python port of R ``drop_empty_footnotes_column``.

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
