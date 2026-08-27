"""Per-run configuration — the resolved settings threaded through every stage.

The config object is a *subset* of the constants plus dataset-specific absolute paths,
exposed as a frozen :class:`Config` dataclass built by :func:`load_pipeline_config`.

Two deliberate simplifications:

* Operational defaults are exposed exactly once, as the full
  :class:`~whep_digitize.setup.constants.Defaults` group — there is no second, narrower
  ``defaults`` set.
* Export file naming is not derived here; see
  :class:`~whep_digitize.setup.constants.OutputConfig` for the suffixes actually used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from whep_digitize.setup.constants import (
    Columns,
    Defaults,
    Files,
    OutputConfig,
    Performance,
    Postpro,
    Sorting,
    get_pipeline_constants,
)
from whep_digitize.setup.helpers.strings import transliterate_ascii_lower
from whep_digitize.setup.paths import project_root

_WHITESPACE_RE = re.compile(r"\s+")
_NON_NAME_RE = re.compile(r"[^a-z0-9 ]")


def normalize_dataset_name(dataset_name: str) -> str:
    """Normalize a dataset name to the canonical ``snake_case`` form.

    Uses the shared policy transliteration (:func:`~whep_digitize.setup.helpers.strings.
    transliterate_ascii_lower` — NFD diacritic strip + lowercase) -> replace non-alphanumeric
    (keeping spaces) with a space -> trim -> collapse whitespace runs to single underscores.
    ``"whep_data_raw"`` round-trips unchanged.

    Args:
        dataset_name: Raw dataset name.

    Returns:
        The normalized dataset name.
    """
    ascii_lower = transliterate_ascii_lower(dataset_name)
    spaced = _NON_NAME_RE.sub(" ", ascii_lower).strip()
    return _WHITESPACE_RE.sub("_", spaced)


@dataclass(frozen=True, slots=True)
class InputPaths:
    """Absolute paths of the four import-stage layer directories."""

    raw: Path
    cleaning: Path
    standardization: Path
    harmonization: Path


@dataclass(frozen=True, slots=True)
class OutputStagePaths:
    """Absolute paths of the export-stage output directories."""

    lists: Path
    processed: Path


@dataclass(frozen=True, slots=True)
class AuditPaths:
    """Absolute paths of the post-processing audit subtree.

    ``dataset_dir`` is an intentional alias of ``audit_dir`` — both resolve to the same path.
    """

    audit_root_dir: Path
    audit_dir: Path
    diagnostics_dir: Path
    templates_dir: Path
    runtime_cache_dir: Path
    dataset_dir: Path
    audit_file_name: str
    audit_file_path: Path


@dataclass(frozen=True, slots=True)
class DataPaths:
    """The three path families under ``data/``. ``input`` / ``output`` name the pipeline data."""

    input: InputPaths
    output: OutputStagePaths
    audit: AuditPaths


@dataclass(frozen=True, slots=True)
class Paths:
    """Root of the resolved path tree."""

    data: DataPaths


@dataclass(frozen=True, slots=True)
class Config:
    """A resolved, per-run pipeline configuration.

    Composes dataset-specific absolute paths with the immutable constant groups the
    stages read (columns, ordering, export settings, performance, post-processing).
    """

    project_root: Path
    dataset_name: str
    paths: Paths
    files: Files
    columns: Columns
    column_required: tuple[str, ...]
    column_id: tuple[str, ...]
    column_order: tuple[str, ...]
    output_config: OutputConfig
    audit_columns: tuple[str, ...]
    performance: Performance
    postpro: Postpro
    sorting: Sorting
    defaults: Defaults
    show_missing_commodity_metadata_warning: bool = False


def load_pipeline_config(
    dataset_name: str | None = None,
    root: Path | str | None = None,
) -> Config:
    """Build the :class:`Config` for a run.

    Args:
        dataset_name: Dataset name; defaults to ``constants.dataset_default_name``.
            Normalized via :func:`normalize_dataset_name`.
        root: Project root; defaults to :func:`~whep_digitize.setup.paths.project_root`.

    Returns:
        A fully resolved, frozen :class:`Config`.
    """
    constants = get_pipeline_constants()
    resolved_root = Path(root).resolve() if root is not None else project_root()
    name = normalize_dataset_name(dataset_name or constants.dataset_default_name)

    path_names = constants.paths
    postpro = constants.postpro
    data_dir = resolved_root / path_names.data_dir

    input_base = data_dir / path_names.input_dir
    input_paths = InputPaths(
        raw=input_base / path_names.input_raw_dir,
        cleaning=input_base / path_names.input_clean_dir,
        standardization=input_base / path_names.input_standardize_dir,
        harmonization=input_base / path_names.input_harmonize_dir,
    )

    output_base = data_dir / path_names.output_dir
    output_paths = OutputStagePaths(
        lists=output_base / path_names.output_lists_dir,
        processed=output_base / path_names.output_processed_dir,
    )

    audit_root = data_dir / path_names.postpro_dir
    audit_dir = audit_root / postpro.audit_dir_name
    audit_file_name = f"{name}{postpro.data_validation_audit_suffix}"
    audit_paths = AuditPaths(
        audit_root_dir=audit_root,
        audit_dir=audit_dir,
        diagnostics_dir=audit_root / postpro.diagnostics_dir_name,
        templates_dir=audit_root / postpro.templates_dir_name,
        runtime_cache_dir=audit_root / postpro.runtime_cache_dir_name,
        dataset_dir=audit_dir,
        audit_file_name=audit_file_name,
        audit_file_path=audit_dir / audit_file_name,
    )

    return Config(
        project_root=resolved_root,
        dataset_name=name,
        paths=Paths(
            data=DataPaths(
                input=input_paths,
                output=output_paths,
                audit=audit_paths,
            )
        ),
        files=constants.files,
        columns=constants.columns,
        column_required=constants.columns.base,
        column_id=constants.columns.id_vars,
        column_order=constants.sorting.stage_row_order,
        output_config=constants.output_config,
        audit_columns=constants.audit_columns,
        performance=constants.performance,
        postpro=postpro,
        sorting=constants.sorting,
        defaults=constants.defaults,
    )
