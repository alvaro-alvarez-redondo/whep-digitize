"""Tests for cross-stage contracts and the wired postpro-runner result shape."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from whep_digitize.contracts import (
    ExportResult,
    ImportDiagnostics,
    ImportResult,
    PostproResult,
    assert_export_paths_contract,
)
from whep_digitize.postpro.runner import run_postpro_pipeline
from whep_digitize.setup.config import Config
from whep_digitize.setup.directories import create_required_directories
from whep_digitize.setup.errors import ContractError, WhepError


def test_import_result_construction() -> None:
    result = ImportResult(
        data=pl.DataFrame({"value": [1.0]}),
        wide_raw=pl.DataFrame({"2000": ["1"]}),
        diagnostics=ImportDiagnostics(warnings=("w",)),
    )
    assert result.data.height == 1
    assert result.diagnostics.warnings == ("w",)


def test_assert_export_paths_contract_ok() -> None:
    result = ExportResult(
        processed_paths={"whep_data_harmonize": Path("out.tsv")},
        lists_paths={"commodity": Path("unique_commodity.xlsx")},
    )
    assert_export_paths_contract(result)  # should not raise


def test_assert_export_paths_contract_rejects_empty() -> None:
    result = ExportResult(processed_paths={}, lists_paths={"c": Path("x.xlsx")})
    with pytest.raises(ContractError):
        assert_export_paths_contract(result)


def test_run_postpro_pipeline_returns_result(config: Config, sample_long_df: pl.DataFrame) -> None:
    create_required_directories(config)  # preflight needs the rule dirs to exist
    result = run_postpro_pipeline(sample_long_df, config)

    assert isinstance(result, PostproResult)
    # No rule files -> clean/harmonize are single-pass no-ops; the frames pass through.
    assert result.clean.height == sample_long_df.height
    assert result.normalize.height == sample_long_df.height
    assert result.harmonize.height == sample_long_df.height
    # The audit stage coerces the value column to Float64.
    assert result.harmonize.schema["value"] == pl.Float64
    # Multi-pass diagnostics are populated for both rule stages.
    assert result.diagnostics.clean.multi_pass is not None
    assert result.diagnostics.harmonize.multi_pass is not None
    # The persisted audit workbook paths are recorded in the diagnostics outputs mapping.
    assert "clean_audit" in result.diagnostics.report_paths


def test_run_postpro_pipeline_canonicalizes_all_string_layer_cells(
    config: Config, sample_long_df: pl.DataFrame
) -> None:
    create_required_directories(config)
    raw = sample_long_df.with_columns(
        pl.Series("polity", ["c; a; b; a", "z; y", "m"], dtype=pl.String),
        pl.Series("unit", ["tonnes", "kg; g; kg", "litre"], dtype=pl.String),
    )

    result = run_postpro_pipeline(raw, config)

    for layer in (result.clean, result.normalize, result.harmonize):
        keyed = layer.sort("document")
        assert keyed.get_column("polity").to_list() == ["a; b; c", "y; z", "m"]
        assert keyed.get_column("unit").to_list() == ["tonnes", "g; kg", "litre"]


def test_run_postpro_pipeline_aborts_on_missing_columns(config: Config) -> None:
    create_required_directories(config)
    with pytest.raises(WhepError):
        # Missing the required unit/commodity columns -> preflight fails.
        run_postpro_pipeline(pl.DataFrame({"value": ["1"]}), config)
