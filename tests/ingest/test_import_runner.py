"""Tests for the ingest stage runner (``ingest.runner.run_import_pipeline``).

Functional coverage: the wired pipeline returns an :class:`ImportResult` on the real corpus
(no more ``StageNotImplementedError``), the long frame is canonically sorted, and an empty
import folder aborts. Byte-for-byte stage parity vs R lives in
``tests/parity/test_import_stage_parity.py``.
"""

from __future__ import annotations

import pytest

from whep_digitize.contracts import ImportResult
from whep_digitize.ingest.runner import run_import_pipeline
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.sorting import sort_pipeline_stage_df


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
