"""Postpro / audit configuration — ports ``r/2-postpro_pipeline/20-data_audit/20-audit-config.R``.

Audit-config validation, the standardized empty audit-findings schema (with the audit-type
identifiers and messages the validators emit), audit-root preparation, and audit output-path
resolution. The R original raised via ``checkmate`` / ``cli_abort``; this port uses the guard
helper (:func:`~whep_digitize.setup.helpers.assertions.require`) and reuses the shared
directory helpers.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.directories import delete_directory_if_exists
from whep_digitize.setup.helpers.assertions import require

# Audit-finding metadata (verbatim R identifiers/messages — parity depends on the exact bytes).
AUDIT_TYPE_CHARACTER_NON_EMPTY = "character_non_empty"
AUDIT_TYPE_NUMERIC_STRING = "numeric_string"
CHARACTER_NON_EMPTY_MESSAGE = "value must be a non-empty character string"
NUMERIC_STRING_MESSAGE = "value must contain only digits and at most one decimal point"

# The findings-table columns (R ``empty_audit_findings_df``). ``row_index`` is 1-based.
AUDIT_FINDINGS_COLUMNS = ("row_index", "audit_column", "audit_type", "audit_message")


def empty_audit_findings() -> pl.DataFrame:
    """Return the standardized empty audit-findings frame.

    The Python port of R ``empty_audit_findings_df()``: a zero-row frame with the fixed
    findings schema, so concatenating validator outputs is always well-typed.

    Returns:
        An empty frame with columns ``row_index`` (Int64), ``audit_column``, ``audit_type``,
        and ``audit_message`` (all String).
    """
    return pl.DataFrame(
        schema={
            "row_index": pl.Int64,
            "audit_column": pl.String,
            "audit_type": pl.String,
            "audit_message": pl.String,
        }
    )


def validate_audit_config(config: Config) -> None:
    """Validate the audit-relevant configuration fields (R ``load_audit_config``).

    The typed :class:`~whep_digitize.setup.config.Config` already guarantees structure; this
    mirrors the R non-empty invariants so a malformed config fails loudly at the same point.

    Args:
        config: The resolved pipeline configuration.

    Raises:
        ValidationError: If ``column_order`` or ``audit_columns`` is empty, or an audit/import
            path is blank.
    """
    require(len(config.column_order) >= 1, "config.column_order must be a non-empty vector")
    require(len(config.audit_columns) >= 1, "config.audit_columns must be a non-empty vector")
    require(
        len(str(config.paths.data.import_.raw)) >= 1,
        "config.paths.data.import.raw must be a non-empty path",
    )
    require(
        len(str(config.paths.data.audit.audit_dir)) >= 1,
        "config.paths.data.audit.audit_dir must be a non-empty path",
    )


def prepare_audit_root(audit_root_dir: Path) -> bool:
    """Remove the previous audit folder if present, tolerating locked/permission-protected files.

    The Python port of R ``prepare_audit_root``: it deletes the audit output folder so each run
    writes into a clean directory, but continues (returning ``False``) when the folder cannot be
    removed instead of aborting.

    Args:
        audit_root_dir: The audit output directory.

    Returns:
        ``True`` if the folder existed and was deleted, ``False`` if it did not exist or a
        tolerated permission/lock error occurred.
    """
    require(len(str(audit_root_dir)) >= 1, "audit_root_dir must be a non-empty path")
    return delete_directory_if_exists(audit_root_dir, tolerate_permission_errors=True)


def resolve_audit_output_paths(audit_root_dir: Path, audit_file_name: str) -> Path:
    """Compute the audit workbook path without creating any directories.

    The Python port of R ``resolve_audit_output_paths`` (which returned a list); only the
    ``audit_file_path`` is needed downstream.

    Args:
        audit_root_dir: The audit output directory.
        audit_file_name: The workbook file name.

    Returns:
        ``audit_root_dir / audit_file_name``.
    """
    require(len(str(audit_root_dir)) >= 1, "audit_root_dir must be a non-empty path")
    require(len(audit_file_name) >= 1, "audit_file_name must be a non-empty string")
    return audit_root_dir / audit_file_name
