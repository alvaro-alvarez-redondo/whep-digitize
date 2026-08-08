r"""Postpro / audit orchestration (``audit_data_output``).

:func:`audit_data_output` runs master validation over the dataset, exports the highlighted
invalid-row workbook when findings exist, and coerces ``value`` to ``Float64`` via
``cast(Float64, strict=False)`` (unparseable values become null rather than raising).

Two behaviors are **deliberate** — do not "fix" either one, both are covered by the test suite:

* Invalid rows are **kept** in the audited output — the frame is the full dataset with ``value``
  parsed, not the invalid subset dropped. Auditing reports, it never filters.
* The audit regex ``^[0-9]+(\.[0-9]+)?$`` is stricter than the float parser, so a value like
  ``"-3.5"`` is **flagged as a finding yet still parses** to ``-3.5`` (not null). Findings flag
  values for human review; they do not decide what the numeric column holds.

:class:`AuditResult` makes the findings table and the written report path first-class alongside
the parsed frame, so callers never have to rely on a side channel.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from whep_digitize.postpro.audit.config import (
    prepare_audit_root,
    resolve_audit_output_paths,
    validate_audit_config,
)
from whep_digitize.postpro.audit.export import export_validation_audit_report
from whep_digitize.postpro.audit.validation import (
    resolve_audit_columns_by_type,
    run_master_validation,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants

_CONSTANTS = get_pipeline_constants()
_VALUE_COLUMN = _CONSTANTS.defaults.value_column
# Internal 1-based row index for subsetting; prefixed to never collide with a dataset column.
_ROW_INDEX_INTERNAL = "__whep_audit_row_index__"


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Result of :func:`audit_data_output`.

    Attributes:
        audited: The full dataset with ``value`` coerced to ``Float64`` (all rows retained;
            unparseable values become null). Identical to the input when there is no ``value``
            column.
        findings: The findings table (1-based ``row_index``, ``audit_column``, ``audit_type``,
            ``audit_message``); empty when the dataset is clean.
        invalid_row_index: Sorted, unique 1-based indices of rows with any finding.
        report_path: Path of the written audit workbook, or ``None`` when no findings existed
            (no file created).
    """

    audited: pl.DataFrame
    findings: pl.DataFrame
    invalid_row_index: tuple[int, ...]
    report_path: Path | None


def audit_data_output(
    dataset: pl.DataFrame,
    config: Config,
    *,
    audit_columns_by_type: Mapping[str, Sequence[str]] | None = None,
) -> AuditResult:
    """Audit the dataset, export findings, and parse ``value`` to numeric.

    Validates the config, clears the audit root, runs master validation, writes the highlighted
    workbook when findings exist, then returns the full dataset with ``value`` parsed (invalid
    rows retained).

    Args:
        dataset: The dataset to audit.
        config: The resolved pipeline configuration.
        audit_columns_by_type: Optional explicit audit-type -> columns mapping; when ``None`` it
            is derived from ``config``.

    Returns:
        An :class:`AuditResult` with the parsed frame, findings, invalid indices, and report path.
    """
    validate_audit_config(config)
    audit_output_dir = config.paths.data.audit.audit_dir
    prepare_audit_root(audit_output_dir)

    columns_by_type = resolve_audit_columns_by_type(config, audit_columns_by_type)
    master = run_master_validation(dataset, columns_by_type)
    findings = master.findings
    invalid_index = master.invalid_row_index

    report_path: Path | None = None
    if findings.height > 0:
        audit_df = _subset_invalid_rows(dataset, invalid_index)
        findings_for_export = _remap_findings_row_index(findings, invalid_index)
        audit_file_path = resolve_audit_output_paths(
            audit_output_dir, config.paths.data.audit.audit_file_path.name
        )
        report_path = export_validation_audit_report(
            audit_df, config, findings_for_export, audit_file_path
        )

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
        report_path=report_path,
    )


def _subset_invalid_rows(dataset: pl.DataFrame, invalid_index: tuple[int, ...]) -> pl.DataFrame:
    """Return the rows at ``invalid_index`` (1-based), preserving original order and schema."""
    if not invalid_index:
        return dataset.clear()
    return (
        dataset.with_row_index(_ROW_INDEX_INTERNAL, offset=1)
        .filter(pl.col(_ROW_INDEX_INTERNAL).cast(pl.Int64).is_in(list(invalid_index)))
        .drop(_ROW_INDEX_INTERNAL)
    )


def _remap_findings_row_index(
    findings: pl.DataFrame, invalid_index: tuple[int, ...]
) -> pl.DataFrame:
    """Remap global ``row_index`` to 1-based positions within the exported invalid subset."""
    mapping = {global_index: local + 1 for local, global_index in enumerate(invalid_index)}
    return findings.with_columns(
        pl.col("row_index").replace_strict(mapping, return_dtype=pl.Int64).alias("row_index")
    )
