"""Centralized pipeline constants, reached through :func:`get_pipeline_constants`.

This module is the single source of truth for every literal the pipeline depends on
(regex patterns, column groups, canonical ordering, post-processing rule settings,
performance thresholds, path names, defaults).

Design notes:

* Constants are immutable nested :func:`dataclasses.dataclass` (``frozen=True``);
  sequences are tuples and mappings are :class:`types.MappingProxyType`. This enforces
  the "treat constants as immutable" contract at the type level.
* :func:`get_pipeline_constants` is memoized with :func:`functools.lru_cache`, so the
  constant set is built once per process and shared by every caller.
* Transliteration is not stored as a constant — it is implemented in
  :mod:`whep_digitize.setup.helpers.strings` as the normalization policy's NFD diacritic
  strip.
* Dependency declarations belong to ``pyproject.toml`` (``uv`` owns them) and progress
  theming is left to ``rich``, so neither has a constant here.
* :attr:`ExportConfig.processed_suffix` is ``".tsv"`` — the extension the processed export
  actually writes. All operational defaults live in the single :class:`Defaults` group.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType

# Column tuples reused across several constant groups. Defined at module level so they
# can serve as immutable dataclass field defaults without a factory.
FIXED_EXPORT_COLUMNS: tuple[str, ...] = (
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "notes",
    "footnotes",
    "yearbook",
    "document",
)
AUDIT_COLUMNS: tuple[str, ...] = (
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "yearbook",
    "document",
)


@dataclass(frozen=True, slots=True)
class Patterns:
    """Regex patterns. Kept as Python raw strings (``re`` / polars ``.str`` compatible)."""

    normalize_non_alnum: str = r"[^a-z0-9;,:()\[\]]+"
    header_normalize_whitespace: str = r"\s+"
    header_normalize_separator_spacing: str = r"\s*([/-])\s*"
    header_normalize_non_alnum: str = r"[^a-z0-9\-/]+"
    header_normalize_multi_underscore: str = r"_{2,}"
    header_normalize_trim_underscore: str = r"^_+|_+$"
    header_normalize_fast_path: str = r"^[a-z0-9](?:[a-z0-9/_-]*[a-z0-9])?$"
    year_column: str = r"^\d{4}(-\d{4})?$"
    yearbook_token_4digit: str = r"^\d{4}$"
    # Audit numeric-string validator. Deliberately stricter than the float parser: rejects
    # negatives / scientific notation / signs, so "-3.5" is flagged by the audit even though
    # it parses fine.
    audit_numeric_string: str = r"^[0-9]+(\.[0-9]+)?$"
    # Leading numeric multiplier in a unit string ("1000 head"): group 1 = the number (digits,
    # dots/commas, optional exponent), group 2 = the base unit.
    standardize_multiplier_prefix: str = r"^(\s*[0-9][0-9.,]*(?:[eE][+-]?[0-9]+)?)[ _-]+(.+)$"
    file_extension: str = r"\.[a-z0-9]+$"


@dataclass(frozen=True, slots=True)
class HeaderNormalization:
    """Header-canonicalization replacements and the source->canonical alias map."""

    whitespace_replacement: str = " "
    # Backreference to group 1, in Python ``re`` replacement syntax.
    separator_replacement: str = r"\1"
    non_alnum_replacement: str = "_"
    trim_underscore_replacement: str = ""
    canonical_aliases: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({"country": "polity"})
    )


@dataclass(frozen=True, slots=True)
class Performance:
    """Performance thresholds. ``import_parallel_workers`` accepts ``"auto"`` or an int."""

    normalize_unique_min_n: int = 256
    normalize_unique_sample_n: int = 2048
    normalize_unique_ratio_threshold: float = 0.85
    import_workbook_batch_size: int = 32
    import_parallel_workers: str | int = "auto"
    import_parallel_workers_auto_token: str = "auto"
    import_parallel_workers_auto_max: int = 8
    import_future_scheduling: int = 4


@dataclass(frozen=True, slots=True)
class Defaults:
    """Operational default values (placeholders for unknown/blank metadata)."""

    unknown_document: str = "(unknown_document)"
    unknown_commodity: str = "(unknown_commodity)"
    list_blank_label: str = "(blank)"
    unknown_filename: str = "unknown"
    value_column: str = "value"
    # The default ``notes`` value is "no note at all", i.e. null.
    notes_value: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectNames:
    """Canonical names of the per-stage data objects (and diagnostic bags)."""

    raw: str = "whep_data_raw"
    wide_raw: str = "whep_data_wide_raw"
    clean: str = "whep_data_clean"
    normalize: str = "whep_data_normalize"
    harmonize: str = "whep_data_harmonize"
    export_paths: str = "export_paths"
    collected_reading_errors: str = "collected_reading_errors"
    collected_errors: str = "collected_errors"
    collected_warnings: str = "collected_warnings"


@dataclass(frozen=True, slots=True)
class Columns:
    """Column-role groups. ``id_vars`` is the identifier set of the wide->long reshape."""

    base: tuple[str, ...] = ("continent", "polity", "unit", "footnotes")
    id_vars: tuple[str, ...] = (
        "commodity",
        "variable",
        "unit",
        "hemisphere",
        "continent",
        "polity",
        "footnotes",
    )
    value: tuple[str, ...] = ("year", "value")
    system: tuple[str, ...] = ("notes", "yearbook", "document")


@dataclass(frozen=True, slots=True)
class Sorting:
    """Canonical business-key row order applied by ``sort_pipeline_stage_df``."""

    stage_row_order: tuple[str, ...] = (
        "hemisphere",
        "continent",
        "polity",
        "commodity",
        "variable",
        "unit",
        "year",
        "value",
        "notes",
        "footnotes",
        "yearbook",
        "document",
    )


@dataclass(frozen=True, slots=True)
class Files:
    """Canonical workbook file names."""

    raw_data: str = "whep_data_raw.xlsx"
    wide_raw_data: str = "whep_data_wide_raw.xlsx"
    long_raw_data: str = "whep_data_long_raw.xlsx"


@dataclass(frozen=True, slots=True)
class PathNames:
    """Relative directory names under ``data/`` (assembled into absolute paths by Config)."""

    data_dir: str = "data"
    import_dir: str = "import"
    import_raw_dir: str = "raw"
    import_clean_dir: str = "clean"
    import_standardize_dir: str = "standardize"
    import_harmonize_dir: str = "harmonize"
    postpro_dir: str = "postpro"
    export_dir: str = "export"
    export_lists_dir: str = "lists"
    export_processed_dir: str = "processed"
    checkpoints_dir: str = ".checkpoints"


@dataclass(frozen=True, slots=True)
class Checkpoints:
    """Crash-recovery checkpoint settings (opt-in via ``RuntimeOptions.checkpointing_enabled``).

    Only the import stage checkpoints: :func:`~whep_digitize.ingest.runner.run_import_pipeline`
    is the sole caller of the save/load helpers. Frames are written as Parquet and composite
    results such as :class:`~whep_digitize.contracts.ImportResult` as pickle.
    """

    import_stage_name: str = "import_pipeline"
    frame_suffix: str = ".parquet"
    object_suffix: str = ".pkl"
    saved_message: str = "Checkpoint saved: {path}"
    restored_message: str = "Checkpoint restored: {path}"


@dataclass(frozen=True, slots=True)
class Tokens:
    """Filename token-parsing constants. ``commodity_start_index`` is 1-based."""

    # 1-based, so Python slicing subtracts 1: parts[commodity_start_index - 1 :].
    commodity_start_index: int = 7


@dataclass(frozen=True, slots=True)
class TimeUnits:
    """Time conversion factors for elapsed-time formatting."""

    seconds_per_minute: int = 60
    seconds_per_hour: int = 3600


@dataclass(frozen=True, slots=True)
class RuleMatchNormalization:
    """When rule match-keys are normalized, and which columns are matched raw."""

    apply_once_before_stage: bool = True
    apply_each_pass: bool = False
    excluded_columns: tuple[str, ...] = ("year", "value", "yearbook", "document")


@dataclass(frozen=True, slots=True)
class TargetUpdateStrategies:
    """Target-update strategy config. ``notes`` concatenates; everything else last-wins."""

    default: str = "last_rule_wins"
    concatenate_delimiter: str = "; "
    by_column: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({"notes": "concatenate"})
    )
    supported: tuple[str, ...] = ("last_rule_wins", "concatenate")


@dataclass(frozen=True, slots=True)
class TargetUpdateFastPath:
    """Fast-path toggles for target updates."""

    last_rule_wins_unique_row_id: bool = True


@dataclass(frozen=True, slots=True)
class MultiPass:
    """Multi-pass clean/harmonize convergence controls."""

    enabled_by_stage: Mapping[str, bool] = field(
        default_factory=lambda: MappingProxyType({"clean": True, "harmonize": True})
    )
    max_passes_by_stage: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({"clean": 10, "harmonize": 10})
    )
    cycle_policy: str = "warn"
    supported_cycle_policies: tuple[str, ...] = ("warn", "abort")
    diagnostics_verbosity: str = "compact"
    supported_diagnostics_verbosity: tuple[str, ...] = ("compact", "verbose")


@dataclass(frozen=True, slots=True)
class RuntimeCache:
    """Rule-payload bundle disk+memory cache (disabled by default).

    The on-disk cache file is ``.parquet`` for portability.
    """

    enabled: bool = False
    cache_file_name: str = "stage_payload_bundle_cache.parquet"
    max_entries: int = 128


@dataclass(frozen=True, slots=True)
class SchemaValidationCache:
    """Memoization of already-validated rule schemas (disabled by default)."""

    enabled: bool = False
    max_entries: int = 1024


@dataclass(frozen=True, slots=True)
class Standardization:
    """Unit-standardization rule-file settings."""

    excluded_sheet_names: tuple[str, ...] = ("master_unit",)
    # Generic fallback commodity key tried when no specific-commodity rule matches.
    all_commodity_key: str = "all commodity"
    required_rule_columns: tuple[str, ...] = (
        "commodity_key",
        "unit_source",
        "unit_target",
        "unit_factor",
        "unit_offset",
    )


@dataclass(frozen=True, slots=True)
class Postpro:
    """Post-processing settings: rule engine, multi-pass, caches, and audit file names."""

    audit_dir_name: str = "audit"
    diagnostics_dir_name: str = "diagnostics"
    templates_dir_name: str = "templates"
    runtime_cache_dir_name: str = "runtime_cache"
    clean_harmonize_template_file_name: str = "clean_harmonize_template.xlsx"
    standardize_units_template_file_name: str = "standardize_units_template.xlsx"
    data_validation_audit_suffix: str = "_data_validation_audit.xlsx"
    clean_audit_file_name: str = "clean_audit.xlsx"
    harmonize_audit_file_name: str = "harmonize_audit.xlsx"
    standardize_audit_file_name: str = "standardize_audit.xlsx"
    last_rule_wins_overwrites_file_name: str = "postpro_last_rule_wins_overwrites.xlsx"
    rule_match_wildcard_token: str = "#ANY#"
    # Rule-authoring directive: prefixing a target-condition value with this marker forces
    # full-string matching for that rule, opting out of `;`-token membership (and out of
    # wildcard interpretation, so a literal "#ANY#" can be matched). Stripped before keying.
    rule_match_exact_token: str = "#EXACT#"
    # The 6 canonical rule columns; value_source is optional.
    canonical_rule_columns: tuple[str, ...] = (
        "column_source",
        "value_source_raw",
        "value_source",
        "column_target",
        "value_target_raw",
        "value_target",
    )
    # Unified source/target result-value column names, shared by every rule stage.
    stage_source_value_column: str = "value_source"
    stage_target_value_column: str = "value_target"
    stage_names: tuple[str, ...] = ("clean", "harmonize")
    standardization: Standardization = field(default_factory=Standardization)
    rule_match_normalization: RuleMatchNormalization = field(default_factory=RuleMatchNormalization)
    target_update_strategies: TargetUpdateStrategies = field(default_factory=TargetUpdateStrategies)
    target_update_fast_path: TargetUpdateFastPath = field(default_factory=TargetUpdateFastPath)
    multi_pass: MultiPass = field(default_factory=MultiPass)
    runtime_cache: RuntimeCache = field(default_factory=RuntimeCache)
    schema_validation_cache: SchemaValidationCache = field(default_factory=SchemaValidationCache)


@dataclass(frozen=True, slots=True)
class ErrorHighlightStyle:
    """Excel style applied to invalid audit cells."""

    fg_fill: str = "#FFB84D"
    font_colour: str = "#000000"
    text_decoration: str = "bold"
    border: str = "TopBottomLeftRight"
    border_colour: str = "#6D4C41"
    border_style: str = "thick"


@dataclass(frozen=True, slots=True)
class ExportConfig:
    """Export settings: which columns become unique lists, which layers are written."""

    list_suffix: str = "_unique.xlsx"
    lists_to_export: tuple[str, ...] = FIXED_EXPORT_COLUMNS
    lists_workbook_name: str = "whep_unique_lists_raw"
    export_layers: tuple[str, ...] = ("harmonize",)
    # The processed export writes .tsv, not a workbook.
    processed_suffix: str = ".tsv"
    error_highlight: ErrorHighlightStyle = field(default_factory=ErrorHighlightStyle)


@dataclass(frozen=True, slots=True)
class Progress:
    """User-facing progress text. Presentation (colors/handlers) is left to ``rich``."""

    update_interval: float = 0.2
    pulse_template: str = "{stage} pass {index}"
    stage_labels: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(
            {
                "setup": "setup",
                "import": "import",
                "postpro": "postpro",
                "export": "export",
            }
        )
    )
    messages: Mapping[str, Mapping[str, str]] = field(
        default_factory=lambda: MappingProxyType(
            {
                "setup": MappingProxyType(
                    {
                        "load_config": "loading pipeline configuration",
                        "create_dirs": "creating required directories",
                    }
                ),
                "import": MappingProxyType(
                    {
                        "reading": "reading source files",
                        "read_file": "reading {name}",
                        "transforming": "transforming source files",
                        "transform_file": "transforming {name}",
                        "dropping": "dropping null-value rows",
                        "validating": "validating transformed records",
                        "splitting": "consolidating validation groups",
                        "sorting": "sorting to canonical order",
                    }
                ),
                "postpro": MappingProxyType(
                    {
                        "audit": "auditing raw data",
                        "init_dirs": "initializing audit directories",
                        "templates": "generating rule templates",
                        "collect_preflight": "collecting preflight checks",
                        "assert_preflight": "asserting preflight checks",
                        "clean": "running clean layer",
                        "standardize": "running standardize layer",
                        "harmonize": "running harmonize layer",
                        "persist": "persisting diagnostics",
                    }
                ),
                "export": MappingProxyType(
                    {
                        "processed": "processed workbooks",
                        "lists": "lists workbooks",
                    }
                ),
            }
        )
    )


@dataclass(frozen=True, slots=True)
class Constants:
    """The complete, immutable pipeline constant set. Access via :func:`get_pipeline_constants`."""

    dataset_default_name: str = "whep_data_raw"
    timestamp_format_utc: str = "%Y-%m-%dT%H:%M:%SZ"
    na_placeholder: str = "..NA_INTERNAL.."
    na_match_key: str = "..NA_MATCH_KEY.."
    fixed_export_columns: tuple[str, ...] = FIXED_EXPORT_COLUMNS
    audit_columns: tuple[str, ...] = AUDIT_COLUMNS
    patterns: Patterns = field(default_factory=Patterns)
    header_normalization: HeaderNormalization = field(default_factory=HeaderNormalization)
    performance: Performance = field(default_factory=Performance)
    defaults: Defaults = field(default_factory=Defaults)
    object_names: ObjectNames = field(default_factory=ObjectNames)
    columns: Columns = field(default_factory=Columns)
    sorting: Sorting = field(default_factory=Sorting)
    files: Files = field(default_factory=Files)
    paths: PathNames = field(default_factory=PathNames)
    checkpoints: Checkpoints = field(default_factory=Checkpoints)
    tokens: Tokens = field(default_factory=Tokens)
    time_units: TimeUnits = field(default_factory=TimeUnits)
    postpro: Postpro = field(default_factory=Postpro)
    export_config: ExportConfig = field(default_factory=ExportConfig)
    progress: Progress = field(default_factory=Progress)


@lru_cache(maxsize=1)
def get_pipeline_constants() -> Constants:
    """Return the cached, immutable pipeline constants.

    The :class:`Constants` instance is built once per process and reused by every caller.
    Treat the result as immutable (it is frozen).

    Returns:
        The singleton :class:`Constants` instance.
    """
    return Constants()
