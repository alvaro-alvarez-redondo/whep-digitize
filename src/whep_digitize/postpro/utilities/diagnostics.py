"""Postpro / utilities — per-layer diagnostics.

:func:`build_layer_diagnostics` summarizes one clean/standardize/harmonize layer's audit table
into a :class:`~whep_digitize.contracts.LayerDiagnostics`.

The contract deliberately carries only deterministic fields — matched/unmatched counts, status,
and message. No wall-clock timestamp is recorded, so identical inputs produce identical
diagnostics. ``layer_name`` and ``rows_out`` are validated as a caller sanity check but do not
feed the returned contract.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.contracts import LayerDiagnostics
from whep_digitize.setup.helpers.assertions import require

_AFFECTED_ROWS = "affected_rows"
_MATCHED_MESSAGE = "Rules applied successfully"
_UNMATCHED_MESSAGE = "No rows matched available rules"


def build_layer_diagnostics(
    layer_name: str, rows_in: int, rows_out: int, audit_df: pl.DataFrame
) -> LayerDiagnostics:
    """Build the diagnostics for one processing layer from its audit table.

    ``matched_count`` is the sum of the audit table's ``affected_rows`` (``0`` when the table is
    empty or lacks the column), ``unmatched_count`` is ``max(rows_in - matched, 0)``, and the
    status/message reflect whether any rows matched at all.

    Args:
        layer_name: The layer label (validated; not stored in the contract).
        rows_in: Row count before processing (drives ``unmatched_count``).
        rows_out: Row count after processing (validated only; not stored in the contract).
        audit_df: The layer's audit table (``affected_rows`` column drives ``matched_count``).

    Returns:
        The :class:`LayerDiagnostics` for the layer (``multi_pass`` is set by the layer driver).

    Raises:
        ValidationError: If ``layer_name`` is blank or a row count is negative.
    """
    require(len(layer_name) >= 1, "layer_name must be a non-empty string")
    require(rows_in >= 0, "rows_in must be non-negative")
    require(rows_out >= 0, "rows_out must be non-negative")

    if audit_df.height == 0 or _AFFECTED_ROWS not in audit_df.columns:
        matched_count = 0
    else:
        matched_count = int(audit_df.get_column(_AFFECTED_ROWS).sum() or 0)

    unmatched_count = max(rows_in - matched_count, 0)
    matched = matched_count > 0
    return LayerDiagnostics(
        matched_count=matched_count,
        unmatched_count=unmatched_count,
        status="pass" if matched else "warn",
        messages=(_MATCHED_MESSAGE if matched else _UNMATCHED_MESSAGE,),
    )
