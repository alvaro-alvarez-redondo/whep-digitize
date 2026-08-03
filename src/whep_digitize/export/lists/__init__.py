"""Export / lists — the per-column unique-value workbook family.

One ``unique_<col>.xlsx`` workbook per exported column, each with one sheet per distinct layer
value-set (identical layers merged into one sheet, e.g. ``raw_clean_normalize_harmonize``).

* :mod:`~whep_digitize.export.lists.unique_values` — sheet order + label inference,
  per-(layer, column) unique values (drop null, code-point sort, ``"(blank)"`` prepended if any
  missing), path build, layer-by-sheet grouping, union columns.
* :mod:`~whep_digitize.export.lists.merge` — configured-column resolution and identical-layer
  merging with fixed sheet order.
* :mod:`~whep_digitize.export.lists.write` — per-column multi-sheet no-header workbook write
  (``xlsxwriter``), unique-value cache, filename-collision guard, and ``export_lists``.
"""

from __future__ import annotations

from whep_digitize.export.lists.merge import (
    resolve_list_sheet_payloads,
    resolve_lists_export_columns,
)
from whep_digitize.export.lists.unique_values import (
    LISTS_SHEET_ORDER,
    build_column_lists_export_path,
    build_layer_tables_by_sheet,
    collect_union_columns,
    compute_unique_column_values,
    infer_layer_sheet_name,
)
from whep_digitize.export.lists.write import (
    build_column_unique_cache,
    export_lists,
    write_column_lists_workbook,
)

__all__ = [
    "LISTS_SHEET_ORDER",
    "build_column_lists_export_path",
    "build_column_unique_cache",
    "build_layer_tables_by_sheet",
    "collect_union_columns",
    "compute_unique_column_values",
    "export_lists",
    "infer_layer_sheet_name",
    "resolve_list_sheet_payloads",
    "resolve_lists_export_columns",
    "write_column_lists_workbook",
]
