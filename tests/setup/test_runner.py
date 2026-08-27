"""Tests for the Stage 0 runner."""

from __future__ import annotations

from pathlib import Path

from whep_digitize.setup.config import Config
from whep_digitize.setup.runner import run_setup_pipeline


def test_run_setup_pipeline_returns_config(project_dir: Path) -> None:
    config = run_setup_pipeline(root=project_dir)
    assert isinstance(config, Config)
    assert config.dataset_name == "whep_data_raw"


def test_run_setup_pipeline_creates_directories(project_dir: Path) -> None:
    config = run_setup_pipeline(root=project_dir)
    assert config.paths.data.input.raw.is_dir()
    assert config.paths.data.audit.audit_dir.is_dir()
    assert config.paths.data.output.processed.is_dir()
