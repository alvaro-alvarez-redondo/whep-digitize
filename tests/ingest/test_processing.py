"""Tests for ingest processing: transform_single_file + read_transform_pipeline_files.

Functional coverage: the per-file transform (including the empty-file and
missing-metadata branches), and the fused read+transform pipeline over the real corpus and
edge cases (empty list, missing column, unreadable file). Reference parity and the
sequential-vs-parallel determinism guarantee live in
``tests/parity/test_processing_parity.py``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from whep_digitize.ingest.transform.processing import (
    ReadTransformResult,
    read_transform_pipeline_files,
    transform_single_file,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError

_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"


def _wide() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "continent": ["europe", "asia"],
            "polity": ["spain", "japan"],
            "unit": ["t", "t"],
            "footnotes": [None, None],
            "hemisphere": ["north", "north"],
            "variable": ["production", "production"],
            "2020": ["20", "30"],
        },
        schema_overrides={"footnotes": pl.String},
    )


# --------------------------------------------------------------------------- transform_single_file


def test_transform_single_file(config: Config) -> None:
    file_row = {"file_name": "f.xlsx", "yearbook": "fao_2020", "commodity": "wheat"}
    result = transform_single_file(file_row, _wide(), config)
    assert result is not None
    assert result.long_raw["commodity"].unique().to_list() == ["wheat"]
    assert result.long_raw["document"].unique().to_list() == ["f.xlsx"]


def test_transform_single_file_empty_returns_none(config: Config) -> None:
    file_row = {"file_name": "f.xlsx", "yearbook": "fao_2020", "commodity": "wheat"}
    assert transform_single_file(file_row, pl.DataFrame(), config) is None


def test_transform_single_file_missing_yearbook_raises(config: Config) -> None:
    file_row = {"file_name": "f.xlsx", "yearbook": None, "commodity": "wheat"}
    with pytest.raises(ValidationError):
        transform_single_file(file_row, _wide(), config)


def test_transform_single_file_missing_commodity_uses_default(config: Config) -> None:
    file_row = {"file_name": "f.xlsx", "yearbook": "fao_2020", "commodity": None}
    result = transform_single_file(file_row, _wide(), config)
    assert result is not None
    # resolve_commodity_name -> "(unknown_commodity)", then normalize_key_fields normalizes it.
    assert result.long_raw["commodity"].unique().to_list() == ["unknown commodity"]


# ------------------------------------------------------------------ read_transform_pipeline_files


def test_read_transform_empty_file_list(config: Config) -> None:
    empty = pl.DataFrame(schema={"file_path": pl.String})
    result = read_transform_pipeline_files(empty, config)
    assert isinstance(result, ReadTransformResult)
    assert result.transformed.long_raw.height == 0
    assert result.errors == ()


def test_read_transform_missing_file_path_column(config: Config) -> None:
    with pytest.raises(ValidationError, match="file_path"):
        read_transform_pipeline_files(pl.DataFrame({"x": ["a"]}), config)


def test_read_transform_single_file(config: Config) -> None:
    wb = _CORPUS / "fao_1949" / "fao_1949_crops" / "r_fao_1949_crops_92_92_date.xlsx"
    file_list = pl.DataFrame(
        {
            "file_path": [wb.as_posix()],
            "file_name": [wb.name],
            "yearbook": ["fao_1949"],
            "commodity": ["date"],
        }
    )
    result = read_transform_pipeline_files(file_list, config)
    assert result.errors == ()
    assert result.transformed.long_raw.height == 45  # matches the single-file transform golden
    assert result.transformed.long_raw["commodity"].unique().to_list() == ["date"]


def test_read_transform_collects_read_errors(config: Config) -> None:
    file_list = pl.DataFrame(
        {
            "file_path": ["does_not_exist.xlsx"],
            "file_name": ["does_not_exist.xlsx"],
            "yearbook": ["fao_2020"],
            "commodity": ["wheat"],
        }
    )
    result = read_transform_pipeline_files(file_list, config)
    # Unreadable file -> read error collected, empty read -> no transform rows.
    assert result.transformed.long_raw.height == 0
    assert any("failed to list sheets" in error for error in result.errors)
