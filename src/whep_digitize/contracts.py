"""Cross-stage data contracts — the stable interfaces between pipeline stages.

Each stage returns a typed, frozen result object instead of the R pattern of assigning
into the global environment and carrying diagnostics as data.table ``attr()``s. Fixing
these contracts up front is what makes the migration parallelizable: a stage can be
built and parity-tested against fixtures as long as it honors its result type.

Contract map (R -> Python):

===============================  ==========================  =========================
R return value                   Python contract             Producer
===============================  ==========================  =========================
``list(data, wide_raw, diag)``   :class:`ImportResult`        :mod:`whep_digitize.ingest`
harmonized dt + attrs            :class:`PostproResult`       :mod:`whep_digitize.postpro`
``list(processed_, lists_)``     :class:`ExportResult`        :mod:`whep_digitize.export`
===============================  ==========================  =========================
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from whep_digitize.setup.errors import ContractError

# --------------------------------------------------------------------------- ingest


@dataclass(frozen=True, slots=True)
class ImportDiagnostics:
    """Non-fatal diagnostics collected during import."""

    reading_errors: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Result of the ingest stage (R ``list(data, wide_raw, diagnostics)``).

    Attributes:
        data: The validated, consolidated long-format frame (character-typed).
        wide_raw: The pre-melt wide frame, retained for diagnostics/export.
        diagnostics: Collected reading/validation errors and warnings.
    """

    data: pl.DataFrame
    wide_raw: pl.DataFrame
    diagnostics: ImportDiagnostics


# --------------------------------------------------------------------------- postpro


@dataclass(frozen=True, slots=True)
class MultiPassDiagnostics:
    """Per-stage multi-pass convergence diagnostics (clean/harmonize)."""

    enabled: bool
    max_passes: int
    passes_executed: int
    converged: bool
    cycle_detected: bool
    max_passes_reached_before_convergence: bool
    cycle_policy: str
    diagnostics_verbosity: str
    stop_reason: str


@dataclass(frozen=True, slots=True)
class LayerDiagnostics:
    """Diagnostics for one post-processing layer (clean / standardize / harmonize)."""

    matched_count: int
    unmatched_count: int
    status: str
    messages: tuple[str, ...] = ()
    multi_pass: MultiPassDiagnostics | None = None


@dataclass(frozen=True, slots=True)
class PostproDiagnostics:
    """Aggregate post-processing diagnostics (R ``pipeline_diagnostics`` attribute)."""

    clean: LayerDiagnostics
    standardize_units: LayerDiagnostics
    harmonize: LayerDiagnostics
    outputs: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PostproResult:
    """Result of the post-processing stage.

    Carries the three intermediate layers explicitly (the R version attached ``clean``
    and ``normalize`` as attributes of the harmonized table).

    Attributes:
        harmonize: The final harmonized frame.
        clean: The clean-layer frame.
        normalize: The unit-standardized ("normalize") frame.
        diagnostics: Aggregate diagnostics for all layers.
    """

    harmonize: pl.DataFrame
    clean: pl.DataFrame
    normalize: pl.DataFrame
    diagnostics: PostproDiagnostics


# --------------------------------------------------------------------------- export


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Result of the export stage (R ``list(processed_paths, lists_paths)``).

    Attributes:
        processed_paths: Mapping of object name -> written processed TSV path.
        lists_paths: Mapping of column name -> written unique-list xlsx path.
    """

    processed_paths: Mapping[str, Path]
    lists_paths: Mapping[str, Path]


def assert_export_paths_contract(result: ExportResult) -> None:
    """Validate the export result contract.

    Args:
        result: The export result to check.

    Raises:
        ContractError: If either path mapping is empty or contains a blank key.
    """
    for label, mapping in (
        ("processed_paths", result.processed_paths),
        ("lists_paths", result.lists_paths),
    ):
        if not mapping:
            raise ContractError(f"export contract violated: {label} is empty")
        if any(not str(key).strip() for key in mapping):
            raise ContractError(f"export contract violated: {label} has a blank key")
