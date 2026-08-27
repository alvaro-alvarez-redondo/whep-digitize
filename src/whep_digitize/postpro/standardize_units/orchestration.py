"""Postpro / standardize_units — stage orchestration.

* rule loading — ``ensure_standardize_template_exists`` / ``read_standardize_rule_workbook`` /
  ``read_all_standardize_rule_files`` / ``load_units_standardization_rules``;
* ``build_standardize_layer_audit`` — merge prepared rules with the engine's matched-rule counts
  into the deterministic audit table;
* ``run_standardize_units_layer_batch`` — load rules → apply → optional duplicate-group
  aggregation → diagnostics + audit, returning a typed :class:`StandardizeLayerResult`.

Rule workbooks are read all-as-text (``pl.read_excel(engine="calamine", infer_schema_length=0)``);
``prepare_standardize_rules`` / the audit coerce the numeric columns, so the read type does not
change rule content.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fastexcel
import polars as pl
from openpyxl import Workbook

from whep_digitize.postpro.standardize_units.aggregation import (
    aggregate_standardized_rows,
    extract_aggregated_rows,
)
from whep_digitize.postpro.standardize_units.engine import apply_standardize_rules
from whep_digitize.postpro.standardize_units.rules_setup import (
    normalize_conversion_rule_columns,
    prepare_standardize_rules,
)
from whep_digitize.postpro.utilities.diagnostics import build_layer_diagnostics
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import ensure_directories_exist
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.frames import canonicalize_semicolon_string_columns
from whep_digitize.setup.helpers.strings import normalize_string

_CONSTANTS = get_pipeline_constants()
_STANDARDIZATION = _CONSTANTS.postpro.standardization
_REQUIRED_COLUMNS = _STANDARDIZATION.required_rule_columns
_EXCLUDED_SHEETS = _STANDARDIZATION.excluded_sheet_names
_TEMPLATE_FILE_NAME = _CONSTANTS.postpro.standardize_units_template_file_name
_RULE_EXTENSIONS = (".xlsx", ".xls")
_AUDIT_SCHEMA: dict[str, type[pl.DataType]] = {
    "affected_rows": pl.Int64,
    "rule_file_identifier": pl.String,
    "commodity_key": pl.String,
    "unit_source": pl.String,
    "unit_target": pl.String,
    "unit_factor": pl.Float64,
    "unit_offset": pl.Float64,
    "source_unit_raw": pl.String,
    "detected_prefix": pl.Float64,
    "unit_factor_effective": pl.Float64,
}


@dataclass(frozen=True, slots=True)
class RuleFilesPayload:
    """Loaded raw rule rows plus their source file paths."""

    rules: pl.DataFrame
    source_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedStandardizeRules:
    """Prepared rules + provenance."""

    layer_rules: pl.DataFrame
    source_paths: tuple[str, ...]
    template_path: Path


@dataclass(frozen=True, slots=True)
class StandardizeDiagnostics:
    """Standardize-layer diagnostics for one layer run."""

    matched_count: int
    unmatched_count: int
    applied_rules: int
    rule_sources: tuple[str, ...]
    status: str
    messages: tuple[str, ...]
    aggregation_enabled: bool
    rows_before_aggregation: int | None
    rows_after_aggregation: int | None
    collapsed_rows_count: int | None
    aggregated_groups_count: int | None


@dataclass(frozen=True, slots=True)
class StandardizeLayerResult:
    """Result of :func:`run_standardize_units_layer_batch`."""

    data: pl.DataFrame
    diagnostics: StandardizeDiagnostics
    audit: pl.DataFrame
    layer_rules: pl.DataFrame
    matched_rule_counts: pl.DataFrame
    aggregated_source_rows: pl.DataFrame


def ensure_standardize_template_exists(config: Config) -> Path:
    """Create the standardize-units template workbook if it does not already exist."""
    templates_dir = config.paths.data.audit.templates_dir
    ensure_directories_exist([templates_dir])
    template_path = templates_dir / _TEMPLATE_FILE_NAME
    if not template_path.exists():
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "units_standardization"
        sheet.append(list(_REQUIRED_COLUMNS))
        workbook.save(template_path)
    return template_path


def read_standardize_rule_workbook(
    rule_path: Path, excluded_sheet_names: tuple[str, ...] = _EXCLUDED_SHEETS
) -> pl.DataFrame:
    """Read every non-excluded rule sheet whose columns match the schema, row-bound in order.

    Args:
        rule_path: The workbook path.
        excluded_sheet_names: Sheet names to skip (compared on normalized names).

    Returns:
        The row-bound matching sheets, with a ``source_rule_sheet`` column.

    Raises:
        ValidationError: If the path is missing, or no sheet remains / matches after exclusions.
    """
    require(rule_path.is_file(), f"standardization rule file does not exist: {rule_path}")
    sheet_names = list(fastexcel.read_excel(str(rule_path)).sheet_names)
    excluded_norm = set(
        normalize_string(
            pl.Series("excluded", list(excluded_sheet_names), dtype=pl.String)
        ).to_list()
    )
    normalized = normalize_string(pl.Series("sheets", sheet_names, dtype=pl.String)).to_list()
    selected = [
        name
        for name, norm in zip(sheet_names, normalized, strict=True)
        if norm not in excluded_norm
    ]
    if not selected:
        raise ValidationError(
            f"No worksheets available for standardization after exclusions: {rule_path}"
        )

    matching: list[pl.DataFrame] = []
    for sheet_name in selected:
        sheet = normalize_conversion_rule_columns(
            pl.read_excel(
                rule_path, sheet_name=sheet_name, engine="calamine", infer_schema_length=0
            )
        )
        if all(column in sheet.columns for column in _REQUIRED_COLUMNS):
            matching.append(
                sheet.select(*_REQUIRED_COLUMNS).with_columns(
                    pl.lit(sheet_name, dtype=pl.String).alias("source_rule_sheet")
                )
            )
    if not matching:
        raise ValidationError(
            f"No worksheets with matching standardization columns found in {rule_path}"
        )
    return pl.concat(matching, how="diagonal")


def read_all_standardize_rule_files(config: Config) -> RuleFilesPayload:
    """Discover and read every standardization rule workbook (deterministically ordered)."""
    standardization_dir = config.paths.data.import_.standardization
    ensure_directories_exist([standardization_dir])
    rule_paths = sorted(
        (
            entry
            for entry in standardization_dir.iterdir()
            if entry.is_file() and entry.suffix.lower() in _RULE_EXTENSIONS
        ),
        key=lambda entry: entry.name,
    )
    if not rule_paths:
        return RuleFilesPayload(rules=pl.DataFrame(), source_paths=())

    frames = [
        read_standardize_rule_workbook(path, _EXCLUDED_SHEETS).with_columns(
            pl.lit(path.name, dtype=pl.String).alias("source_rule_file")
        )
        for path in rule_paths
    ]
    return RuleFilesPayload(
        rules=pl.concat(frames, how="diagonal"),
        source_paths=tuple(path.resolve().as_posix() for path in rule_paths),
    )


def load_units_standardization_rules(config: Config) -> LoadedStandardizeRules:
    """Ensure the template exists, read + prepare the conversion rules."""
    template_path = ensure_standardize_template_exists(config)
    payload = read_all_standardize_rule_files(config)
    prepared = prepare_standardize_rules(payload.rules)
    source_paths = payload.source_paths if payload.source_paths else (template_path.as_posix(),)
    return LoadedStandardizeRules(prepared, source_paths, template_path)


def build_standardize_layer_audit(
    layer_rules_df: pl.DataFrame,
    matched_rule_counts_df: pl.DataFrame,
    source_paths: tuple[str, ...],
) -> pl.DataFrame:
    """Merge prepared rules with matched-rule counts into the standardize audit table.

    Args:
        layer_rules_df: Prepared conversion rules.
        matched_rule_counts_df: The engine's ``matched_rule_counts``.
        source_paths: Source rule-file paths (basename fallback for ``rule_file_identifier``).

    Returns:
        The audit table (empty 10-column frame when no rules or no matches).
    """
    if layer_rules_df.height == 0:
        return pl.DataFrame(schema=_AUDIT_SCHEMA)

    rules = _ensure_audit_rule_columns(layer_rules_df, source_paths)
    counts = _ensure_audit_count_columns(matched_rule_counts_df)

    merged = rules.join(
        counts,
        left_on=["commodity_match_key", "unit_source_key"],
        right_on=["rule_commodity_match_key", "unit_source_key"],
        how="inner",
    )
    if merged.height == 0:
        return pl.DataFrame(schema=_AUDIT_SCHEMA)

    return merged.select(
        pl.col("affected_rows").cast(pl.Int64),
        pl.col("source_rule_file").cast(pl.String).alias("rule_file_identifier"),
        pl.col("applied_commodity_match_key").cast(pl.String).alias("commodity_key"),
        pl.col("unit_source").cast(pl.String),
        pl.col("unit_target").cast(pl.String),
        _audit_numeric_expr("unit_factor"),
        _audit_numeric_expr("unit_offset"),
        pl.col("source_unit_raw").cast(pl.String),
        pl.col("detected_prefix").cast(pl.Float64),
        pl.col("unit_factor_effective").cast(pl.Float64),
    )


def attach_standardize_diagnostics(
    standardized_df: pl.DataFrame,
    clean_rows_count: int,
    matched_count: int,
    unmatched_count: int,
    rules_count: int,
    rule_sources: tuple[str, ...],
    *,
    aggregation_enabled: bool = False,
    rows_before_aggregation: int | None = None,
    rows_after_aggregation: int | None = None,
) -> StandardizeDiagnostics:
    """Build the standardize-layer diagnostics."""
    audit_rows = [matched_count] if matched_count > 0 else []
    audit_df = pl.DataFrame(
        {"affected_rows": pl.Series("affected_rows", audit_rows, dtype=pl.Int64)}
    )
    base = build_layer_diagnostics(
        "standardize_units", clean_rows_count, standardized_df.height, audit_df
    )

    messages = ("no numeric standardization rules found",) if rules_count == 0 else base.messages
    aggregating = aggregation_enabled and rows_before_aggregation is not None
    collapsed: int | None = None
    if aggregating and rows_before_aggregation is not None and rows_after_aggregation is not None:
        collapsed = rows_before_aggregation - rows_after_aggregation
    return StandardizeDiagnostics(
        matched_count=base.matched_count,
        unmatched_count=unmatched_count,
        applied_rules=rules_count,
        rule_sources=tuple(dict.fromkeys(rule_sources)),
        status=base.status,
        messages=messages,
        aggregation_enabled=aggregation_enabled,
        rows_before_aggregation=rows_before_aggregation if aggregating else None,
        rows_after_aggregation=rows_after_aggregation if aggregating else None,
        collapsed_rows_count=collapsed,
        aggregated_groups_count=rows_after_aggregation if aggregating else None,
    )


def run_standardize_units_layer_batch(
    clean_df: pl.DataFrame,
    config: Config,
    *,
    unit_column: str = "unit",
    value_column: str = "value",
    commodity_column: str = "commodity",
    aggregate_after_standardize: bool = True,
) -> StandardizeLayerResult:
    """Run the standardize-units layer: load rules, apply, aggregate, build diagnostics + audit.

    Args:
        clean_df: The clean-layer dataset.
        config: The resolved pipeline configuration.
        unit_column: The unit column name.
        value_column: The numeric value column name.
        commodity_column: The commodity column name.
        aggregate_after_standardize: Collapse duplicate groups (sum the measure) after converting.

    Returns:
        The :class:`StandardizeLayerResult`.
    """
    loaded = load_units_standardization_rules(config)
    applied = apply_standardize_rules(
        clean_df, loaded.layer_rules, unit_column, value_column, commodity_column
    )

    data = canonicalize_semicolon_string_columns(applied.data)
    rows_before = data.height
    aggregated_source_rows = data.clear()
    if aggregate_after_standardize and rows_before > 0:
        aggregated_source_rows = extract_aggregated_rows(data, value_column)
        data = aggregate_standardized_rows(data, value_column)
    rows_after = data.height

    diagnostics = attach_standardize_diagnostics(
        data,
        clean_df.height,
        applied.matched_count,
        applied.unmatched_count,
        loaded.layer_rules.height,
        loaded.source_paths,
        aggregation_enabled=aggregate_after_standardize,
        rows_before_aggregation=rows_before,
        rows_after_aggregation=rows_after,
    )
    audit = build_standardize_layer_audit(
        loaded.layer_rules, applied.matched_rule_counts, loaded.source_paths
    )
    return StandardizeLayerResult(
        data=data,
        diagnostics=diagnostics,
        audit=audit,
        layer_rules=loaded.layer_rules,
        matched_rule_counts=applied.matched_rule_counts,
        aggregated_source_rows=aggregated_source_rows,
    )


def _audit_numeric_expr(column: str) -> pl.Expr:
    """Coerce a string/numeric column expression to ``Float64`` (audit factor/offset)."""
    return (
        pl.col(column)
        .cast(pl.String)
        .str.strip_chars()
        .cast(pl.Float64, strict=False)
        .alias(column)
    )


def _ensure_audit_rule_columns(rules: pl.DataFrame, source_paths: tuple[str, ...]) -> pl.DataFrame:
    """Add the rule-side columns the audit merge needs when a manual rule table omits them."""
    additions: list[pl.Expr] = []
    if "source_rule_file" not in rules.columns:
        fallback = Path(source_paths[0]).name if source_paths else None
        additions.append(pl.lit(fallback, dtype=pl.String).alias("source_rule_file"))
    if "commodity_match_key" not in rules.columns:
        additions.append(pl.col("commodity_key").cast(pl.String).alias("__commodity_key_raw__"))
    if "unit_source_key" not in rules.columns:
        additions.append(pl.col("unit_source").cast(pl.String).alias("__unit_source_raw__"))
    rules = rules.with_columns(additions) if additions else rules
    if "commodity_match_key" not in rules.columns:
        rules = rules.with_columns(
            normalize_string(rules.get_column("__commodity_key_raw__")).alias("commodity_match_key")
        ).drop("__commodity_key_raw__")
    if "unit_source_key" not in rules.columns:
        rules = rules.with_columns(
            normalize_string(rules.get_column("__unit_source_raw__")).alias("unit_source_key")
        ).drop("__unit_source_raw__")
    return rules


def _ensure_audit_count_columns(counts: pl.DataFrame) -> pl.DataFrame:
    """Return the matched-rule counts with the audit-required columns present (nulls if absent)."""
    key_columns = {"rule_commodity_match_key", "applied_commodity_match_key", "unit_source_key"}
    if not key_columns.issubset(counts.columns):
        return pl.DataFrame(
            schema={
                "rule_commodity_match_key": pl.String,
                "applied_commodity_match_key": pl.String,
                "unit_source_key": pl.String,
                "affected_rows": pl.Int64,
                "source_unit_raw": pl.String,
                "detected_prefix": pl.Float64,
                "unit_factor_effective": pl.Float64,
            }
        )
    defaults = {
        "affected_rows": pl.Int64,
        "source_unit_raw": pl.String,
        "detected_prefix": pl.Float64,
        "unit_factor_effective": pl.Float64,
    }
    additions = [
        pl.lit(None, dtype=dtype).alias(column)
        for column, dtype in defaults.items()
        if column not in counts.columns
    ]
    return counts.with_columns(additions) if additions else counts
