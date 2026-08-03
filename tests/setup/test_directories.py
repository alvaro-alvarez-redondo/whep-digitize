"""Tests for directory construction."""

from __future__ import annotations

from pathlib import Path

from whep_digitize.setup.config import Config
from whep_digitize.setup.directories import (
    create_required_directories,
    delete_directory_if_exists,
)


def test_creates_import_and_export_dirs(config: Config) -> None:
    create_required_directories(config)
    assert config.paths.data.import_.raw.is_dir()
    assert config.paths.data.export.processed.is_dir()
    assert config.paths.data.export.lists.is_dir()


def test_creates_audit_subtree(config: Config) -> None:
    create_required_directories(config)
    audit = config.paths.data.audit
    assert audit.audit_dir.is_dir()
    assert audit.diagnostics_dir.is_dir()
    assert audit.templates_dir.is_dir()
    assert audit.runtime_cache_dir.is_dir()


def test_audit_root_excluded_from_targets(config: Config) -> None:
    created = create_required_directories(config)
    audit = config.paths.data.audit
    # The audit root is not an explicit target (created lazily), though its children
    # do bring it into existence via parents=True.
    assert audit.audit_root_dir not in created
    assert audit.audit_dir in created


def test_file_path_collapses_to_parent_dir(config: Config) -> None:
    create_required_directories(config)
    audit = config.paths.data.audit
    # audit_file_path is a file path; only its parent directory should be created.
    assert audit.audit_dir.is_dir()
    assert not audit.audit_file_path.exists()


def test_delete_directory_if_exists(tmp_path: Path) -> None:
    target = tmp_path / "scratch"
    target.mkdir()
    assert delete_directory_if_exists(target) is True
    assert not target.exists()
    # Deleting a non-existent directory is a no-op returning False.
    assert delete_directory_if_exists(target) is False
