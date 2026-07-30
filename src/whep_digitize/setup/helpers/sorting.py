"""Canonical sorting — the Python port of ``02-sorting.R``.

Provides deterministic, stable row ordering by the canonical business-key column order.
polars sorts by Unicode code point (locale-independent), which matches R's radix/C-locale
``setorderv`` for the ASCII-normalized keys the pipeline produces.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants


def sort_pipeline_stage_df(
    frame: pl.DataFrame,
    sort_columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Sort a stage frame by the canonical column order, nulls last.

    Only columns present in ``frame`` are used, in canonical order. Sorting is stable
    (``maintain_order=True``) so the result is deterministic across runs and worker counts.

    Args:
        frame: The frame to sort.
        sort_columns: Column order to sort by; defaults to the canonical
            ``stage_row_order``.

    Returns:
        The sorted frame (unchanged if no sort columns are present).
    """
    order = (
        sort_columns
        if sort_columns is not None
        else get_pipeline_constants().sorting.stage_row_order
    )
    present = [column for column in order if column in frame.columns]
    if not present:
        return frame
    return frame.sort(present, nulls_last=True, maintain_order=True)
