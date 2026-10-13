"""Tests for the export-stage runner (``export.runner.run_export_pipeline``).

Verifies the wired runner produces a valid :class:`OutputResult` (processed-data TSV for the
harmonize layer + per-column unique-list workbooks), creates the export directories, honors the
optional ``raw`` layer, and passes the export-paths contract.
"""

from __future__ import annotations

import polars as pl
from openpyxl import load_workbook

from whep_digitize.contracts import (
    LayerDiagnostics,
    PostproDiagnostics,
    PostproResult,
    assert_output_paths_contract,
)
from whep_digitize.export.runner import run_export_pipeline
from whep_digitize.setup.config import Config


def _postpro_result() -> PostproResult:
    layer = pl.DataFrame(
        {
            "continent": ["europe", "asia"],
            "polity": ["spain", "japan"],
            "year": ["2000", "2001"],
            "value": ["1", "2"],
        }
    )
    harmonize = layer.with_columns(pl.col("value").cast(pl.Float64))
    diag = LayerDiagnostics(matched_count=0, unmatched_count=0, status="ok")
    return PostproResult(
        harmonize=harmonize,
        clean=layer,
        normalize=layer,
        diagnostics=PostproDiagnostics(clean=diag, standardize_units=diag, harmonize=diag),
    )


def test_run_export_pipeline_returns_valid_result(config: Config) -> None:
    result = run_export_pipeline(config, _postpro_result())

    assert_output_paths_contract(result)  # does not raise
    # Every layer is exported. `raw` is absent here because no import frame was supplied.
    assert sorted(result.processed_paths) == [
        "whep_data_clean",
        "whep_data_harmonize",
        "whep_data_normalize",
    ]
    assert result.processed_paths["whep_data_harmonize"].is_file()
    # Default lists_to_export keeps only the categorical columns present (continent, polity).
    assert set(result.lists_paths) == {"continent", "polity"}
    assert all(path.is_file() for path in result.lists_paths.values())


def test_run_export_pipeline_creates_export_directories(config: Config) -> None:
    # The runner is responsible for creating the export dirs (they do not exist yet).
    assert not config.paths.data.output.processed.exists()
    run_export_pipeline(config, _postpro_result())
    assert config.paths.data.output.processed.is_dir()
    assert config.paths.data.output.lists.is_dir()


def test_run_export_pipeline_includes_raw_layer(config: Config) -> None:
    raw = pl.DataFrame(
        {
            "continent": ["Europe", "Asia"],
            "polity": ["Spain", "Japan"],
            "year": ["2000", "2001"],
            "value": ["1", "2"],
        }
    )
    result = run_export_pipeline(config, _postpro_result(), raw=raw)

    # With an un-normalized raw layer, the raw values differ, so "raw" is its own sheet.
    workbook = load_workbook(result.lists_paths["polity"], read_only=True)
    sheet_names = workbook.sheetnames
    workbook.close()
    assert "raw" in sheet_names[0]
    assert sheet_names == ["raw", "clean_normalize_harmonize"]


def test_run_export_pipeline_drops_all_null_columns_per_layer(config: Config) -> None:
    # "hemisphere" is entirely null in every layer and must be dropped everywhere. "polity" is
    # only entirely null in "clean" -- harmonize (and raw) must keep it, proving the drop is
    # evaluated independently per layer rather than as one shared column set.
    clean = pl.DataFrame(
        {
            "hemisphere": pl.Series([None, None], dtype=pl.String),
            "polity": pl.Series([None, None], dtype=pl.String),
            "continent": pl.Series(["europe", "asia"], dtype=pl.String),
            "year": pl.Series(["2000", "2001"], dtype=pl.String),
            "value": pl.Series(["1", "2"], dtype=pl.String),
        }
    )
    harmonize = clean.with_columns(pl.Series("polity", ["spain", "japan"], dtype=pl.String))
    diag = LayerDiagnostics(matched_count=0, unmatched_count=0, status="ok")
    postpro = PostproResult(
        harmonize=harmonize,
        clean=clean,
        normalize=clean,
        diagnostics=PostproDiagnostics(clean=diag, standardize_units=diag, harmonize=diag),
    )
    raw = harmonize

    result = run_export_pipeline(config, postpro, raw=raw)

    for object_name in ("whep_data_raw", "whep_data_clean", "whep_data_normalize"):
        columns = pl.read_csv(
            result.processed_paths[object_name], separator="\t", infer_schema_length=0
        ).columns
        assert "hemisphere" not in columns, f"{object_name} kept an all-null column"
    clean_columns = pl.read_csv(
        result.processed_paths["whep_data_clean"], separator="\t", infer_schema_length=0
    ).columns
    assert "polity" not in clean_columns
    harmonize_columns = pl.read_csv(
        result.processed_paths["whep_data_harmonize"], separator="\t", infer_schema_length=0
    ).columns
    assert "polity" in harmonize_columns, "harmonize's own 'polity' values must survive"


def test_run_export_pipeline_canonicalizes_all_named_layers(config: Config) -> None:
    layer = pl.DataFrame(
        {
            "continent": pl.Series(["z; a; z"], dtype=pl.String),
            "polity": pl.Series(["c; b; c"], dtype=pl.String),
            "year": pl.Series(["2000"], dtype=pl.String),
            "value": pl.Series([1.0], dtype=pl.Float64),
        }
    )
    diag = LayerDiagnostics(matched_count=0, unmatched_count=0, status="ok")
    postpro = PostproResult(
        harmonize=layer,
        clean=layer,
        normalize=layer,
        diagnostics=PostproDiagnostics(clean=diag, standardize_units=diag, harmonize=diag),
    )
    raw = layer.with_columns(pl.Series("continent", ["d; a; d"], dtype=pl.String))

    result = run_export_pipeline(config, postpro, raw=raw)

    expected = {
        "whep_data_raw": ("a; d", "b; c"),
        "whep_data_clean": ("a; z", "b; c"),
        "whep_data_normalize": ("a; z", "b; c"),
        "whep_data_harmonize": ("a; z", "b; c"),
    }
    for object_name, (continent, polity) in expected.items():
        exported = pl.read_csv(
            result.processed_paths[object_name], separator="\t", infer_schema_length=0
        )
        assert exported.get_column("continent").to_list() == [continent]
        assert exported.get_column("polity").to_list() == [polity]


def _iso_whep_postpro(iso_values: list[str | None]) -> PostproResult:
    layer = pl.DataFrame(
        {
            "continent": pl.Series(["europe", "asia"], dtype=pl.String),
            "iso_whep": pl.Series(iso_values, dtype=pl.String),
            "polity": pl.Series(["spain", "japan"], dtype=pl.String),
            "year": pl.Series(["2000", "2001"], dtype=pl.String),
            "value": pl.Series(["1", "2"], dtype=pl.String),
        }
    )
    diag = LayerDiagnostics(matched_count=0, unmatched_count=0, status="ok")
    return PostproResult(
        harmonize=layer,
        clean=layer,
        normalize=layer,
        diagnostics=PostproDiagnostics(clean=diag, standardize_units=diag, harmonize=diag),
    )


def test_populated_iso_whep_is_exported_in_order_and_listed(config: Config) -> None:
    result = run_export_pipeline(config, _iso_whep_postpro(["ESP", "JPN"]))

    columns = pl.read_csv(
        result.processed_paths["whep_data_harmonize"], separator="\t", infer_schema_length=0
    ).columns
    assert columns == ["continent", "iso_whep", "polity", "year", "value"]

    # It is a configured list column, so it gets its own unique-values workbook.
    assert "iso_whep" in result.lists_paths
    assert result.lists_paths["iso_whep"].name == "unique_iso_whep.xlsx"
    # No raw layer was supplied, so the `raw` sheet is empty; the layers share the other one.
    workbook = load_workbook(result.lists_paths["iso_whep"])
    values = [row[0] for row in workbook["clean_normalize_harmonize"].iter_rows(values_only=True)]
    workbook.close()
    assert values == ["ESP", "JPN"]


def test_empty_iso_whep_is_left_out_of_every_export(config: Config) -> None:
    # While nothing populates iso_whep it is entirely null, and the all-null drop removes it from
    # the TSVs; with no layer carrying it, the lists export skips it rather than failing.
    result = run_export_pipeline(config, _iso_whep_postpro([None, None]))

    for path in result.processed_paths.values():
        columns = pl.read_csv(path, separator="\t", infer_schema_length=0).columns
        assert "iso_whep" not in columns
    assert "iso_whep" not in result.lists_paths
    assert {"continent", "polity"} <= set(result.lists_paths)
