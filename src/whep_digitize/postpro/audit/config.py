"""Postpro / audit configuration.

Audit-config validation, the standardized empty audit-findings schema (with the audit-type
identifiers and messages the validators emit), audit-root preparation, and audit report-path
resolution. Invariants are enforced through the guard helper
(:func:`~whep_digitize.setup.helpers.assertions.require`) and the shared directory helpers.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.directories import delete_directory_if_exists
from whep_digitize.setup.helpers.assertions import require

# Audit-finding metadata. These exact bytes reach the findings table and the exported workbook,
# so they are part of the output contract — do not reword them.
AUDIT_TYPE_CHARACTER_NON_EMPTY = "character_non_empty"
AUDIT_TYPE_NUMERIC_STRING = "numeric_string"
CHARACTER_NON_EMPTY_MESSAGE = "value must be a non-empty character string"
NUMERIC_STRING_MESSAGE = "value must contain only digits and at most one decimal point"

# The findings-table columns. ``row_index`` is 1-based.
AUDIT_FINDINGS_COLUMNS = ("row_index", "audit_column", "audit_type", "audit_message")


def empty_audit_findings() -> pl.DataFrame:
    """Return the standardized empty audit-findings frame.

    A zero-row frame carrying the fixed findings schema, so concatenating validator outputs is
    always well-typed even when every validator finds nothing.

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
    """Validate the audit-relevant configuration fields.

    The typed :class:`~whep_digitize.setup.config.Config` already guarantees structure; this
    re-checks the non-empty invariants so a malformed config fails loudly here, before any
    audit work or directory deletion happens.

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

    Deletes the audit folder so each run writes into a clean directory, but continues
    (returning ``False``) when the folder cannot be removed instead of aborting — a workbook left
    open in Excel must not fail the whole run.

    Args:
        audit_root_dir: The audit directory.

    Returns:
        ``True`` if the folder existed and was deleted, ``False`` if it did not exist or a
        tolerated permission/lock error occurred.
    """
    require(len(str(audit_root_dir)) >= 1, "audit_root_dir must be a non-empty path")
    return delete_directory_if_exists(audit_root_dir, tolerate_permission_errors=True)


def resolve_audit_paths(audit_root_dir: Path, audit_file_name: str) -> Path:
    """Compute the audit workbook path without creating any directories.

    A pure path computation: only the workbook path is needed downstream, and the directory is
    created later by the export step.

    Args:
        audit_root_dir: The audit directory.
        audit_file_name: The workbook file name.

    Returns:
        ``audit_root_dir / audit_file_name``.
    """
    require(len(str(audit_root_dir)) >= 1, "audit_root_dir must be a non-empty path")
    require(len(audit_file_name) >= 1, "audit_file_name must be a non-empty string")
    return audit_root_dir / audit_file_name
