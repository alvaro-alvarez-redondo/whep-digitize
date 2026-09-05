r"""Postpro / audit orchestration (``audit_dataset``).

:func:`audit_dataset` runs master validation over the dataset and coerces ``value`` to
``Float64`` via ``cast(Float64, strict=False)`` (unparseable values become null rather than
raising). No workbook is exported; validation findings are returned in the result object.

Two behaviors are **deliberate** — do not "fix" either one, both are covered by the test suite:

* Invalid rows are **kept** in the audited output — the frame is the full dataset with ``value``
  parsed, not the invalid subset dropped. Auditing reports, it never filters.
* The audit regex ``^[0-9]+(\.[0-9]+)?$`` is stricter than the float parser, so a value like
  ``"-3.5"`` is **flagged as a finding yet still parses** to ``-3.5`` (not null). Findings flag
  values for human review; they do not decide what the numeric column holds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.audit.config import (
    prepare_audit_root,
    validate_audit_config,
)
from whep_digitize.postpro.audit.validation import (
    resolve_audit_columns_by_type,
    run_master_validation,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants

_CONSTANTS = get_pipeline_constants()
_VALUE_COLUMN = _CONSTANTS.defaults.value_column


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Result of :func:`audit_dataset`.

    Attributes:
        audited: The full dataset with ``value`` coerced to ``Float64`` (all rows retained;
            unparseable values become null). Identical to the input when there is no ``value``
            column.
        findings: The findings table (1-based ``row_index``, ``audit_column``, ``audit_type``,
            ``audit_message``); empty when the dataset is clean.
        invalid_row_index: Sorted, unique 1-based indices of rows with any finding.
    """

    audited: pl.DataFrame
    findings: pl.DataFrame
    invalid_row_index: tuple[int, ...]


def audit_dataset(
    dataset: pl.DataFrame,
    config: Config,
    *,
    audit_columns_by_type: Mapping[str, Sequence[str]] | None = None,
) -> AuditResult:
    """Audit the dataset and parse ``value`` to numeric.

    Validates the config, clears the audit root, runs master validation, then returns the full
    dataset with ``value`` parsed (invalid rows retained). No workbook is exported.

    Args:
        dataset: The dataset to audit.
        config: The resolved pipeline configuration.
        audit_columns_by_type: Optional explicit audit-type -> columns mapping; when ``None`` it
            is derived from ``config``.

    Returns:
        An :class:`AuditResult` with the parsed frame, findings, and invalid indices.
    """
    validate_audit_config(config)
    audit_dir = config.paths.data.audit.audit_dir
    prepare_audit_root(audit_dir)

    columns_by_type = resolve_audit_columns_by_type(config, audit_columns_by_type)
    master = run_master_validation(dataset, columns_by_type)
    findings = master.findings
    invalid_index = master.invalid_row_index

    audited = dataset
    if _VALUE_COLUMN in audited.columns:
        audited = audited.with_columns(
            pl.col(_VALUE_COLUMN)
            .cast(pl.String)
            .cast(pl.Float64, strict=False)
            .alias(_VALUE_COLUMN)
        )

    return AuditResult(
        audited=audited,
        findings=findings,
        invalid_row_index=invalid_index,
    )
