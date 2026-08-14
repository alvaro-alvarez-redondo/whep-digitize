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
from whep_digitize.setup.helpers.strings import canonicalize_token_column

_CONSTANTS = get_pipeline_constants()
_CONCAT_DELIMITER = _CONSTANTS.postpro.target_update_strategies.concatenate_delimiter
_TRIM_CHARS = " \t\r\n"
_ANNOTATION_COLUMNS = ("notes", "footnotes")
_FOOTNOTES_COLUMN = "footnotes"


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
        canonicalize_token_column(dataset.get_column(column), _CONCAT_DELIMITER)
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
