"""Postpro / diagnostics — end-of-stage duplicate audit.

Flags rows that repeat within a layer frame under two criteria and exports one TSV per layer
into ``data/postpro/duplicates/``:

* ``dup_full`` — the row is identical to at least one other row across **every** column;
* ``dup_excl_value`` — the row is identical to at least one other row across every column
  **except** ``value``.

Only rows satisfying ``dup_excl_value`` are exported, since ``dup_full`` is a strict subset of
it: two rows identical everywhere are necessarily identical everywhere but ``value``. A row with
``dup_excl_value`` true and ``dup_full`` false is the interesting case — the same record carrying
a conflicting ``value``.

Null equality follows polars' grouping semantics: two nulls in the same column count as equal,
so rows that are jointly missing a field still register as duplicates.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import ensure_directories_exist
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.numeric import format_float_columns

_CONSTANTS = get_pipeline_constants()
_POSTPRO = _CONSTANTS.postpro
_VALUE_COLUMN = _CONSTANTS.defaults.value_column
# Record separator for TSV output: platform newline, matching the other pipeline TSV writers.
_FWRITE_EOL: str = "\r\n" if os.name == "nt" else "\n"
DUP_FULL_COLUMN = "dup_full"
DUP_EXCL_VALUE_COLUMN = "dup_excl_value"
_FLAG_COLUMNS = (DUP_FULL_COLUMN, DUP_EXCL_VALUE_COLUMN)


def build_duplicate_audit(
    frame: pl.DataFrame, *, value_column: str = _VALUE_COLUMN
) -> pl.DataFrame:
    """Return the duplicated rows of ``frame``, flagged with both duplication criteria.

    A row is kept when it matches at least one other row on every column except
    ``value_column``. Both flags are appended: ``dup_full`` (identical across all columns) and
    ``dup_excl_value`` (identical across all columns but ``value_column``). ``dup_excl_value``
    is true for every returned row by construction; it is emitted anyway so the exported file
    is self-describing.

    Row order is the input's order, so a deterministic input yields a deterministic audit.

    Args:
        frame: The layer frame to analyse.
        value_column: The column excluded by the second criterion. When it is absent from
            ``frame`` the two criteria coincide and both flags are identical.

    Returns:
        The duplicated subset with the two boolean flag columns appended. Empty (header only)
        when ``frame`` holds no duplicates, is empty, or has no comparable key columns.

    Raises:
        ValidationError: If ``frame`` already carries a column named ``dup_full`` or
            ``dup_excl_value``, which the audit would otherwise silently overwrite.
    """
    for flag in _FLAG_COLUMNS:
        require(
            flag not in frame.columns,
            f"frame must not already contain the reserved audit column '{flag}'",
        )

    key_columns = [name for name in frame.columns if name != value_column]
    # ``is_duplicated`` needs at least one column to group on, and an all-null comparison over
    # zero keys is meaningless anyway: a frame that is nothing but ``value`` has no identity to
    # duplicate. Both that case and an empty frame yield the header-only result.
    if not key_columns or frame.height == 0:
        return _empty_audit(frame)

    duplicated_excluding_value = frame.select(key_columns).is_duplicated()
    duplicated_fully = (
        frame.is_duplicated() if len(key_columns) != frame.width else duplicated_excluding_value
    )
    return frame.with_columns(
        duplicated_fully.alias(DUP_FULL_COLUMN),
        duplicated_excluding_value.alias(DUP_EXCL_VALUE_COLUMN),
    ).filter(duplicated_excluding_value)


def persist_duplicate_audits(
    layers: Mapping[str, pl.DataFrame],
    config: Config,
    *,
    value_column: str = _VALUE_COLUMN,
) -> dict[str, Path]:
    """Build and write one duplicate-audit TSV per layer.

    Every layer produces a file, including layers with no duplicates — those are written with
    the header row only, so a consumer can tell "audited, nothing found" from "never ran".

    The per-layer audits are independent, so they are built concurrently on a thread pool:
    polars releases the GIL for the grouping work, and threads avoid the frame pickling a
    process pool would cost. Writing stays on the calling thread, keeping file creation ordered
    and the output deterministic.

    Args:
        layers: Layer name → frame, e.g. ``{"clean": clean_df}``. The name becomes the file
            stem, suffixed with ``_dup.tsv``.
        config: The resolved pipeline configuration.
        value_column: The column excluded by the ``dup_excl_value`` criterion.

    Returns:
        Mapping of layer name → written path, in the iteration order of ``layers``.
    """
    duplicates_dir = config.paths.data.audit.duplicates_dir
    ensure_directories_exist([duplicates_dir])

    names = list(layers)
    if not names:
        return {}

    def audit_layer(name: str) -> pl.DataFrame:
        return build_duplicate_audit(layers[name], value_column=value_column)

    with ThreadPoolExecutor(max_workers=min(len(names), os.cpu_count() or 1)) as pool:
        audits = list(pool.map(audit_layer, names))

    output_paths: dict[str, Path] = {}
    for name, audit in zip(names, audits, strict=True):
        path = duplicates_dir / f"{name}{_POSTPRO.duplicates_file_suffix}"
        _write_duplicates_tsv(path, audit)
        output_paths[name] = path
    return output_paths


# --------------------------------------------------------------------------- private helpers


def _empty_audit(frame: pl.DataFrame) -> pl.DataFrame:
    """Return a zero-row frame carrying ``frame``'s schema plus the two boolean flag columns."""
    schema: dict[str, pl.DataType] = dict(frame.schema)
    schema[DUP_FULL_COLUMN] = pl.Boolean()
    schema[DUP_EXCL_VALUE_COLUMN] = pl.Boolean()
    return pl.DataFrame(schema=schema)


def _write_duplicates_tsv(path: Path, frame: pl.DataFrame) -> None:
    """Write one duplicate audit to a tab-separated ``.tsv`` file.

    Floats are rendered with the pipeline's fixed-notation double rendering, so a duplicate
    audit and the processed export agree on how a value is spelled.
    """
    format_float_columns(frame).write_csv(path, separator="\t", line_terminator=_FWRITE_EOL)
