"""Tests for the ingest stage runner (``ingest.runner.run_import_pipeline``).

Functional coverage: the wired pipeline returns an :class:`ImportResult` on the real corpus
(no more ``StageNotImplementedError``), the long frame is canonically sorted, an empty
import folder aborts, and the opt-in checkpoint round-trips (and stays inert when off).
Exact stage parity vs the reference lives in ``tests/parity/test_import_stage_parity.py``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from whep_digitize.contracts import ImportDiagnostics, ImportResult
from whep_digitize.ingest.runner import run_import_pipeline
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.checkpoints import checkpoint_path, save_checkpoint
from whep_digitize.setup.helpers.sorting import sort_pipeline_stage_df
from whep_digitize.setup.options import RuntimeOptions

_CHECKPOINT_NAME = get_pipeline_constants().checkpoints.import_stage_name


def test_run_import_pipeline_corpus(corpus_config: Config) -> None:
    result = run_import_pipeline(corpus_config, current_year=2025)
    assert isinstance(result, ImportResult)
    assert result.data.height > 0
    assert result.wide_raw.height > 0
    # consolidated long frame is in the canonical column order
    assert result.data.columns == list(corpus_config.column_order)
    assert result.diagnostics.reading_errors == ()
    assert len(result.diagnostics.validation_errors) > 0  # sparse footnotes -> mandatory errors
    assert result.diagnostics.warnings == ()


def test_run_import_pipeline_output_is_sorted(corpus_config: Config) -> None:
    result = run_import_pipeline(corpus_config, current_year=2025)
    # The result is already canonically sorted -> re-sorting is a no-op.
    assert sort_pipeline_stage_df(result.data).equals(result.data)


def test_run_import_pipeline_no_files_aborts(config: Config) -> None:
    config.paths.data.import_.raw.mkdir(parents=True, exist_ok=True)  # empty raw folder
    with pytest.raises(ValidationError, match="no excel files were found"):
        run_import_pipeline(config)


# ------------------------------------------------------------------------ checkpointing


def _import_checkpoint(config: Config) -> Path:
    """The import-stage checkpoint file (pickle — an ``ImportResult`` is not a frame)."""
    return checkpoint_path(_CHECKPOINT_NAME, config, is_frame=False)


def test_run_import_pipeline_checkpoint_round_trip(config: Config, corpus_config: Config) -> None:
    # `corpus_config` derives from `config`, so both share the temp project root (hence the same
    # checkpoint dir) and differ only in the raw import folder.
    options = RuntimeOptions(checkpointing_enabled=True, progress_enabled=False)
    first = run_import_pipeline(corpus_config, options, current_year=2025)
    assert _import_checkpoint(corpus_config).exists()

    # An empty raw folder aborts, so returning `first` proves the restore short-circuited the
    # stage ahead of discovery.
    config.paths.data.import_.raw.mkdir(parents=True, exist_ok=True)
    restored = run_import_pipeline(config, options, current_year=2025)
    assert restored.data.equals(first.data)
    assert restored.wide_raw.equals(first.wide_raw)
    assert restored.diagnostics == first.diagnostics


def test_run_import_pipeline_checkpointing_off_writes_nothing(corpus_config: Config) -> None:
    options = RuntimeOptions(checkpointing_enabled=False, progress_enabled=False)
    run_import_pipeline(corpus_config, options, current_year=2025)
    checkpoint = _import_checkpoint(corpus_config)
    assert not checkpoint.exists()
    assert not checkpoint.parent.exists()  # the .checkpoints dir is never created


def test_run_import_pipeline_checkpointing_off_reads_nothing(
    config: Config, sample_long_df: pl.DataFrame
) -> None:
    stale = ImportResult(
        data=sample_long_df, wide_raw=sample_long_df, diagnostics=ImportDiagnostics()
    )
    save_checkpoint(_CHECKPOINT_NAME, stale, config, enabled=True)
    config.paths.data.import_.raw.mkdir(parents=True, exist_ok=True)
    options = RuntimeOptions(checkpointing_enabled=False, progress_enabled=False)
    # The checkpoint is on disk but the flag is off: the stage runs and hits the empty folder.
    with pytest.raises(ValidationError, match="no excel files were found"):
        run_import_pipeline(config, options)
