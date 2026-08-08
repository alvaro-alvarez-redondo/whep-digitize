r"""Postpro / audit validators.

The non-empty and numeric-string validators, the validation plan, the master validation
registry, and audit-column resolution. Row indices are **1-based** so findings line up with the
exported invalid-row subset and with the spreadsheet rows a human reads.

The numeric-string validator uses ``^[0-9]+(\.[0-9]+)?$`` (constant
:attr:`~whep_digitize.setup.constants.Patterns.audit_numeric_string`), which is deliberately
stricter than the float parser used downstream — negative, signed, and scientific-notation
values are flagged here yet still parse in :mod:`whep_digitize.postpro.audit.audit`.

Every validator is pure: it reads the frame and returns a findings frame, never mutating input.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.audit.config import (
    AUDIT_TYPE_CHARACTER_NON_EMPTY,
    AUDIT_TYPE_NUMERIC_STRING,
    CHARACTER_NON_EMPTY_MESSAGE,
    NUMERIC_STRING_MESSAGE,
    empty_audit_findings,
    validate_audit_config,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require

_CONSTANTS = get_pipeline_constants()
_NUMERIC_STRING_PATTERN = _CONSTANTS.patterns.audit_numeric_string
_VALUE_COLUMN = _CONSTANTS.defaults.value_column
# The whitespace class used for blank detection: space, tab, CR, LF only — deliberately not the
# full Unicode whitespace set, so exotic separators are not silently treated as blank.
_TRIM_CHARS = " \t\r\n"
# Internal row-index column (1-based), prefixed to never collide with a dataset column.
_ROW_INDEX_INTERNAL = "__whep_audit_row_index__"


@dataclass(frozen=True, slots=True)
class MasterValidationResult:
    """Result of :func:`run_master_validation`.

    Attributes:
        findings: The findings table (``row_index`` 1-based, ``audit_column``, ``audit_type``,
            ``audit_message``), one row per failing cell, in validation-plan order.
        invalid_row_index: The sorted, unique 1-based indices of rows with any finding.
    """

    findings: pl.DataFrame
    invalid_row_index: tuple[int, ...]


def _invalid_row_indices(dataset: pl.DataFrame, mask: pl.Expr) -> list[int]:
    """Return the 1-based indices of the rows matching ``mask``, in frame order."""
    return (
        dataset.with_row_index(_ROW_INDEX_INTERNAL, offset=1)
        .filter(mask)
        .get_column(_ROW_INDEX_INTERNAL)
        .cast(pl.Int64)
        .to_list()
    )


def _findings(
    row_index: list[int], column_name: str, audit_type: str, message: str
) -> pl.DataFrame:
    """Build a findings frame for one column/validator, or the empty frame when there are none."""
    if not row_index:
        return empty_audit_findings()
    height = len(row_index)
    return pl.DataFrame(
        {
            "row_index": pl.Series("row_index", row_index, dtype=pl.Int64),
            "audit_column": pl.Series("audit_column", [column_name] * height, dtype=pl.String),
            "audit_type": pl.Series("audit_type", [audit_type] * height, dtype=pl.String),
            "audit_message": pl.Series("audit_message", [message] * height, dtype=pl.String),
        }
    )


def audit_character_non_empty(dataset: pl.DataFrame, column_name: str) -> pl.DataFrame:
    """Flag rows whose ``column_name`` value is null or blank after trimming.

    A value fails when it is null, or when trimming leaves an empty string.

    Args:
        dataset: The dataset to audit.
        column_name: The column to check.

    Returns:
        A findings frame (``audit_type = "character_non_empty"``), empty if all values are
        non-blank.

    Raises:
        ValidationError: If ``column_name`` is empty or absent from ``dataset``.
    """
    require(len(column_name) >= 1, "column_name must be a non-empty string")
    require(column_name in dataset.columns, f"column '{column_name}' is missing from the dataset")

    column = pl.col(column_name).cast(pl.String)
    mask = column.is_null() | (column.str.strip_chars(_TRIM_CHARS).str.len_chars() == 0)
    invalid = _invalid_row_indices(dataset, mask)
    return _findings(
        invalid, column_name, AUDIT_TYPE_CHARACTER_NON_EMPTY, CHARACTER_NON_EMPTY_MESSAGE
    )


def audit_numeric_string(dataset: pl.DataFrame, column_name: str = _VALUE_COLUMN) -> pl.DataFrame:
    """Flag non-null rows whose ``column_name`` value is not a plain numeric string.

    A value fails when it is non-null and does not match the stricter-than-parser pattern. Null
    values are **not** flagged — absence is a separate concern from malformed text.

    Args:
        dataset: The dataset to audit.
        column_name: The column to check (defaults to ``"value"``).

    Returns:
        A findings frame (``audit_type = "numeric_string"``), empty if all non-null values match.

    Raises:
        ValidationError: If ``column_name`` is empty or absent from ``dataset``.
    """
    require(len(column_name) >= 1, "column_name must be a non-empty string")
    require(column_name in dataset.columns, f"column '{column_name}' is missing from the dataset")

    column = pl.col(column_name).cast(pl.String)
    mask = column.is_not_null() & ~column.str.contains(_NUMERIC_STRING_PATTERN)
    invalid = _invalid_row_indices(dataset, mask)
    return _findings(invalid, column_name, AUDIT_TYPE_NUMERIC_STRING, NUMERIC_STRING_MESSAGE)


# Master validation registry: audit-type identifier -> validator.
_REGISTRY: dict[str, Callable[[pl.DataFrame, str], pl.DataFrame]] = {
    AUDIT_TYPE_CHARACTER_NON_EMPTY: audit_character_non_empty,
    AUDIT_TYPE_NUMERIC_STRING: audit_numeric_string,
}


def build_audit_validation_plan(
    audit_columns_by_type: Mapping[str, Sequence[str]], supported: Sequence[str]
) -> pl.DataFrame:
    """Expand an audit-type -> columns mapping into a one-row-per-(type, column) plan.

    Args:
        audit_columns_by_type: Mapping of audit type to the columns it validates.
        supported: The supported audit types to include, in application order.

    Returns:
        A frame with columns ``audit_type`` and ``column_name``, one row per type/column pair.

    Raises:
        ValidationError: If ``supported`` is empty or any supported type maps to no columns.
    """
    require(len(audit_columns_by_type) >= 1, "audit_columns_by_type must be non-empty")
    require(len(supported) >= 1, "supported must be a non-empty vector")

    audit_types: list[str] = []
    column_names: list[str] = []
    for audit_type in supported:
        columns = audit_columns_by_type.get(audit_type)
        if not columns:
            raise ValidationError(
                "each supported audit type must map to a non-empty character vector of columns"
            )
        for column_name in columns:
            audit_types.append(audit_type)
            column_names.append(column_name)

    return pl.DataFrame(
        {
            "audit_type": pl.Series("audit_type", audit_types, dtype=pl.String),
            "column_name": pl.Series("column_name", column_names, dtype=pl.String),
        }
    )


def run_master_validation(
    dataset: pl.DataFrame,
    audit_columns_by_type: Mapping[str, Sequence[str]],
    selected_validations: Sequence[str] | None = None,
) -> MasterValidationResult:
    """Execute the configured validators and collect their findings.

    Unsupported audit types are skipped with a warning rather than aborting the run;
    ``selected_validations`` (when given) further restricts execution. Findings are concatenated
    in validation-plan order.

    Args:
        dataset: The dataset to audit.
        audit_columns_by_type: Mapping of audit type to the columns it validates. Its key order
            drives the supported-type order.
        selected_validations: Optional subset of validation types to execute.

    Returns:
        A :class:`MasterValidationResult` with the findings table and sorted unique invalid
        row indices.

    Raises:
        ValidationError: If ``audit_columns_by_type`` is empty, or ``selected_validations`` is
            given but empty.
    """
    require(len(audit_columns_by_type) >= 1, "audit_columns_by_type must be non-empty")

    audit_types = list(audit_columns_by_type.keys())
    supported = [audit_type for audit_type in audit_types if audit_type in _REGISTRY]
    unsupported = [audit_type for audit_type in audit_types if audit_type not in _REGISTRY]
    if unsupported:
        warnings.warn(
            f"unsupported audit types were skipped: {', '.join(unsupported)}", stacklevel=2
        )

    if selected_validations is not None:
        require(
            len(selected_validations) >= 1,
            "selected_validations must be non-empty when provided",
        )
        selected = set(selected_validations)
        supported = [audit_type for audit_type in supported if audit_type in selected]

    if not supported:
        return MasterValidationResult(empty_audit_findings(), ())

    plan = build_audit_validation_plan(audit_columns_by_type, supported)
    findings_frames = [
        _REGISTRY[audit_type](dataset, column_name) for audit_type, column_name in plan.iter_rows()
    ]

    findings = pl.concat(findings_frames, how="vertical")
    if findings.height == 0:
        findings = empty_audit_findings()

    invalid_row_index = tuple(sorted(set(findings.get_column("row_index").to_list())))
    return MasterValidationResult(findings, invalid_row_index)


def resolve_audit_columns_by_type(
    config: Config,
    audit_columns_by_type: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Resolve the audit columns grouped by validator type.

    An explicit override is returned as given; otherwise the default mapping is built from
    ``config.audit_columns`` (deduplicated, order preserved) and ``config.column_order`` — the
    numeric-string validator is registered only when a ``"value"`` column is present.

    Args:
        config: The resolved pipeline configuration.
        audit_columns_by_type: Optional explicit mapping; when ``None`` the default is derived
            from ``config``.

    Returns:
        Mapping of audit type to the columns it validates.
    """
    validate_audit_config(config)

    if audit_columns_by_type is not None:
        return {key: tuple(columns) for key, columns in audit_columns_by_type.items()}

    numeric_columns = (_VALUE_COLUMN,) if _VALUE_COLUMN in config.column_order else ()
    return {
        AUDIT_TYPE_CHARACTER_NON_EMPTY: tuple(dict.fromkeys(config.audit_columns)),
        AUDIT_TYPE_NUMERIC_STRING: numeric_columns,
    }
