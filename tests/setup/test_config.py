"""Tests for config construction and path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from whep_digitize.setup.config import Config, load_pipeline_config, normalize_dataset_name


def test_default_dataset_name(config: Config) -> None:
    assert config.dataset_name == "whep_data_raw"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("whep_data_raw", "whep_data_raw"),
        ("WHEP Data Ráw!", "whep_data_raw"),
        ("  Fao   1961  ", "fao_1961"),
        ("Café/Región", "cafe_region"),
    ],
)
def test_normalize_dataset_name(raw: str, expected: str) -> None:
    assert normalize_dataset_name(raw) == expected


def test_input_paths(config: Config, project_dir: Path) -> None:
    data = project_dir / "data"
    assert config.paths.data.input.raw == data / "input" / "raw"
    assert config.paths.data.input.cleaning == data / "input" / "clean"
    assert config.paths.data.input.standardization == data / "input" / "standardize"
    assert config.paths.data.input.harmonization == data / "input" / "harmonize"


def test_audit_subtree_paths(config: Config, project_dir: Path) -> None:
    audit = config.paths.data.audit
    postpro_root = project_dir / "data" / "postpro"
    assert audit.audit_root_dir == postpro_root
    assert audit.audit_dir == postpro_root / "audit"
    assert audit.diagnostics_dir == postpro_root / "diagnostics"
    assert audit.templates_dir == postpro_root / "templates"
    assert audit.runtime_cache_dir == postpro_root / "runtime_cache"
    assert audit.dataset_dir == audit.audit_dir  # intentional alias of audit_dir


def test_audit_file_path(config: Config) -> None:
    audit = config.paths.data.audit
    assert audit.audit_file_name == "whep_data_raw_data_validation_audit.xlsx"
    assert audit.audit_file_path == audit.audit_dir / audit.audit_file_name


def test_column_order_matches_constants(config: Config) -> None:
    assert config.column_order == config.sorting.stage_row_order
    assert config.column_required == config.columns.base


def test_dataset_name_flows_into_audit_file(project_dir: Path) -> None:
    config = load_pipeline_config(dataset_name="FAO 1961", root=project_dir)
    assert config.dataset_name == "fao_1961"
    assert config.paths.data.audit.audit_file_name == "fao_1961_data_validation_audit.xlsx"
