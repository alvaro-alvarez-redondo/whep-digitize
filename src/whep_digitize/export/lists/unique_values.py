"""Unique-list building blocks.

The fixed layer sheet order, the object-name -> sheet-label inference, the per-column
unique-value computation (drop null, code-point sort, ``"(blank)"`` prepended when any value is
missing), the workbook-path build, the layer-by-sheet grouping, and the union-of-columns
collection. All ordering is by Unicode code point (equivalently, UTF-8 byte order) and therefore
locale-independent — part of the pipeline's determinism contract. One visible consequence:
accented values sort *after* every ASCII one.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.numeric import format_double_fixed
from whep_digitize.setup.helpers.strings import normalize_filename

# Fixed sheet order for lists workbooks. Also the order in which layers are grouped into
# merged sheets.
LISTS_SHEET_ORDER: tuple[str, ...] = ("raw", "clean", "normalize", "harmonize")
_LIST_BLANK_LABEL = get_pipeline_constants().defaults.list_blank_label


def infer_layer_sheet_name(object_name: str) -> str:
    """Infer the canonical sheet label (``raw`` / ``clean`` / ``normalize`` / ``harmonize``).

    The first layer suffix the name ends in wins.

    Args:
        object_name: A layer object name (e.g. ``"whep_data_harmonize"``).

    Returns:
        The layer sheet label.

    Raises:
        ValidationError: If the name ends in no known layer suffix.
    """
    for layer in LISTS_SHEET_ORDER:
        if object_name.endswith(f"_{layer}"):
            return layer
    raise ValidationError(f"unable to infer layer sheet name from object '{object_name}'")


def build_column_lists_export_path(config: Config, column_name: str) -> Path:
    """Resolve the ``unique_<column>.xlsx`` path for a column's list workbook.

    The stem is the ``unique_`` prefix plus the normalized column name (the misformatted
    ``export_config.list_suffix`` constant is dead code and deliberately unused). The directory
    is not created here (the runner ensures it).

    Args:
        config: The resolved pipeline configuration.
        column_name: The column whose workbook path is built.

    Returns:
        ``<config.paths.data.export.lists>/unique_<normalized_name>.xlsx``.

    Raises:
        ValidationError: If ``column_name`` is empty.
    """
    if not column_name:
        raise ValidationError("column_name must be a non-empty string")
    return config.paths.data.export.lists / f"unique_{normalize_filename(column_name)}.xlsx"


def compute_unique_column_values(
    frame: pl.DataFrame,
    column_name: str,
    blank_label: str = _LIST_BLANK_LABEL,
) -> list[str]:
    """Return one layer's sorted unique values for a column, as strings.

    Missing (null) values are dropped and, when any were present, ``blank_label`` is prepended
    *after* the sort, so it is never sorted in. Sorting is by code point for text and numeric for
    numbers; a float column is rendered via
    :func:`~whep_digitize.setup.helpers.numeric.format_double_fixed`, the same double formatter the
    processed-data TSVs use. An absent column yields ``[]``.

    Args:
        frame: The layer frame.
        column_name: The column to summarize.
        blank_label: Display placeholder for missing values (default ``"(blank)"``).

    Returns:
        The ordered unique values (blank placeholder first when any value was missing).
    """
    if column_name not in frame.columns:
        return []

    series = frame.get_column(column_name)
    has_missing = series.null_count() > 0
    sorted_values = series.drop_nulls().unique().sort()

    if sorted_values.dtype == pl.String:
        values = sorted_values.to_list()
    elif sorted_values.dtype.is_float():
        values = [format_double_fixed(value) for value in sorted_values.to_list()]
    else:
        values = sorted_values.cast(pl.String).to_list()

    return [blank_label, *values] if has_missing else values


def build_layer_tables_by_sheet(
    layer_tables: Mapping[str, pl.DataFrame],
) -> dict[str, pl.DataFrame]:
    """Key detected layer tables by sheet label, filling missing layers with empty frames.

    Multiple objects mapping to the same sheet label (e.g. two ``*_raw`` tables) are unioned
    rather than dropped, matching on column name and filling the gaps where their schemas differ
    (``pl.concat(how="diagonal")``); absent layers become an empty :class:`polars.DataFrame`.

    Args:
        layer_tables: Detected layer tables keyed by object name.

    Returns:
        A dict keyed by :data:`LISTS_SHEET_ORDER`, each a (possibly empty) frame.
    """
    if not layer_tables:
        return {sheet: pl.DataFrame() for sheet in LISTS_SHEET_ORDER}

    inferred = {name: infer_layer_sheet_name(name) for name in layer_tables}
    by_sheet: dict[str, pl.DataFrame] = {}
    for sheet in LISTS_SHEET_ORDER:
        names = [name for name in layer_tables if inferred[name] == sheet]
        if not names:
            by_sheet[sheet] = pl.DataFrame()
        elif len(names) == 1:
            by_sheet[sheet] = layer_tables[names[0]]
        else:
            by_sheet[sheet] = pl.concat([layer_tables[name] for name in names], how="diagonal")
    return by_sheet


def collect_union_columns(layer_by_sheet: Mapping[str, pl.DataFrame]) -> list[str]:
    """Return the code-point-sorted union of column names across all layer sheets.

    The ordering is by code point, so it does not depend on the ambient locale.

    Args:
        layer_by_sheet: Layer frames keyed by sheet label.

    Returns:
        The sorted, unique column names.
    """
    columns = {column for frame in layer_by_sheet.values() for column in frame.columns}
    return sorted(columns)
