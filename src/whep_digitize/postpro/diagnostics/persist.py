"""Postpro / diagnostics — cross-stage diagnostics assembly + persistence.

* :func:`build_postpro_diagnostics` — the clean / harmonize / standardize matched-rule summaries;
* :func:`persist_postpro_logs` — write the per-stage logs TSVs.

Logs files are written as tab-separated values (TSV) via polars, into the ``logs`` subdirectory
of the post-processing output root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from whep_digitize.postpro.diagnostics.rule_summaries import (
    build_stage_rule_catalog_from_payloads,
    build_unmatched_rule_summary,
    merge_stage_rule_summaries,
    summarize_stage_rules,
)
from whep_digitize.postpro.diagnostics.standardize_summaries import (
    build_standardize_rule_catalog,
    build_unmatched_standardize_rule_summary,
    merge_standardize_rule_summaries,
    summarize_standardize_rules,
)
from whep_digitize.postpro.utilities.audit_roots import initialize_postpro_audit_root
from whep_digitize.postpro.utilities.templates import load_stage_rule_payloads
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import ensure_directories_exist
from whep_digitize.setup.helpers.numeric import format_float_columns

_CONSTANTS = get_pipeline_constants()
_POSTPRO = _CONSTANTS.postpro
_TRIM_CHARS = " \t\r\n"
# Record separator for TSV output: platform newline.
_FWRITE_EOL: str = "\r\n" if os.name == "nt" else "\n"
# Column renames applied when writing clean/harmonize logs TSVs.
_CLEAN_HARM_RENAMES = {
    "rule_file_identifier": "file",
    "affected_rows": "rows",
}
# Standardize logs workbook column subset + renames (applied before writing).
_STANDARDIZE_EXCEL_COLUMNS = (
    "affected_rows",
    "rule_file_identifier",
    "commodity_key",
    "unit_source",
    "unit_target",
    "unit_factor",
    "unit_factor_effective",
    "unit_offset",
)
_STANDARDIZE_RENAMES = {
    "rule_file_identifier": "file",
    "affected_rows": "rows",
    "unit_factor_effective": "unit_factor_net",
}


@dataclass(frozen=True, slots=True)
class PostproDiagnosticsSummaries:
    """The three stage matched-rule summaries."""

    clean_rule_summary: pl.DataFrame
    harmonize_rule_summary: pl.DataFrame
    standardize_rule_summary: pl.DataFrame


def build_postpro_diagnostics(
    clean_audit_df: pl.DataFrame,
    harmonize_audit_df: pl.DataFrame,
    standardize_audit_df: pl.DataFrame,
) -> PostproDiagnosticsSummaries:
    """Summarize the clean / harmonize / standardize audits."""
    return PostproDiagnosticsSummaries(
        clean_rule_summary=summarize_stage_rules(clean_audit_df),
        harmonize_rule_summary=summarize_stage_rules(harmonize_audit_df),
        standardize_rule_summary=summarize_standardize_rules(standardize_audit_df),
    )


def persist_postpro_logs(
    clean_audit_df: pl.DataFrame,
    harmonize_audit_df: pl.DataFrame,
    standardize_audit_df: pl.DataFrame,
    standardize_rules_df: pl.DataFrame,
    config: Config,
    *,
    standardize_matched_rule_counts_df: pl.DataFrame | None = None,
) -> dict[str, Path]:
    """Write the per-stage logs TSVs.

    Args:
        clean_audit_df: The clean-stage audit.
        harmonize_audit_df: The harmonize-stage audit.
        standardize_audit_df: The standardize-stage audit.
        standardize_rules_df: The prepared standardize-layer rules.
        config: The resolved pipeline configuration.
        standardize_matched_rule_counts_df: Optional standardize matched-rule counts.

    Returns:
        Mapping of logs name → written path.
    """
    diagnostics = build_postpro_diagnostics(
        clean_audit_df, harmonize_audit_df, standardize_audit_df
    )
    paths = initialize_postpro_audit_root(config)
    ensure_directories_exist([paths.logs_dir])

    output_paths = {
        "clean_logs": paths.logs_dir / _POSTPRO.clean_logs_file_name,
        "harmonize_logs": paths.logs_dir / _POSTPRO.harmonize_logs_file_name,
        "standardize_logs": paths.logs_dir / _POSTPRO.standardize_logs_file_name,
    }
    clean_catalog = build_stage_rule_catalog_from_payloads(
        load_stage_rule_payloads(config, "clean")
    )
    harmonize_catalog = build_stage_rule_catalog_from_payloads(
        load_stage_rule_payloads(config, "harmonize")
    )
    standardize_catalog = build_standardize_rule_catalog(standardize_rules_df)

    clean_unmatched = build_unmatched_rule_summary(clean_catalog, diagnostics.clean_rule_summary)
    harmonize_unmatched = build_unmatched_rule_summary(
        harmonize_catalog, diagnostics.harmonize_rule_summary
    )
    standardize_unmatched = build_unmatched_standardize_rule_summary(
        standardize_catalog,
        diagnostics.standardize_rule_summary,
        standardize_matched_rule_counts_df,
    )

    clean_merged = merge_stage_rule_summaries(
        diagnostics.clean_rule_summary, clean_unmatched
    )
    _write_logs_tsv(output_paths["clean_logs"], clean_merged.rename(_CLEAN_HARM_RENAMES))

    harmonize_merged = merge_stage_rule_summaries(
        diagnostics.harmonize_rule_summary, harmonize_unmatched
    )
    _write_logs_tsv(
        output_paths["harmonize_logs"], harmonize_merged.rename(_CLEAN_HARM_RENAMES)
    )

    standardize_merged = merge_standardize_rule_summaries(
        diagnostics.standardize_rule_summary, standardize_unmatched
    )
    _write_logs_tsv(
        output_paths["standardize_logs"],
        _standardize_excel_subset(standardize_merged).rename(_STANDARDIZE_RENAMES),
    )

    return output_paths


# --------------------------------------------------------------------------- private helpers


def _standardize_excel_subset(frame: pl.DataFrame) -> pl.DataFrame:
    """Select the standardize logs workbook column subset."""
    return frame.select(_STANDARDIZE_EXCEL_COLUMNS)


def _write_logs_tsv(path: Path, frame: pl.DataFrame) -> None:
    """Write a single frame to a tab-separated ``.tsv`` file.

    Float columns are rendered with the pipeline's fixed-notation double rendering.
    """
    ensure_directories_exist([path.parent])
    format_float_columns(frame).write_csv(
        path, separator="\t", line_terminator=_FWRITE_EOL
    )



