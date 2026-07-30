"""Parity test: the fused read+transform pipeline must match the R golden byte-for-byte.

Discovers the whole corpus and runs ``read_transform_pipeline_files`` both sequentially and in
parallel (``ProcessPoolExecutor``), asserting the combined long frame of every workbook equals
R's ``read_transform_pipeline_files`` output — and that parallel output equals sequential
output regardless of worker count (the determinism guarantee). The parallel run uses one batch
per file so more than one batch (and worker) is actually engaged; if the pool cannot start it
degrades to sequential, so the assertion holds either way.

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import dataclasses
import json

import polars as pl
import pytest
from polars.testing import assert_series_equal
from r_harness import FIXTURES_DIR
from registry import CAPTURES

from whep_digitize.ingest.file_io.discovery import discover_files
from whep_digitize.ingest.transform.processing import (
    ReadTransformResult,
    read_transform_pipeline_files,
)
from whep_digitize.setup.config import Config, load_pipeline_config
from whep_digitize.setup.options import RuntimeOptions

_SPEC = CAPTURES["processing"]
_VALUE_COLUMNS = (
    "commodity",
    "variable",
    "unit",
    "hemisphere",
    "continent",
    "polity",
    "footnotes",
    "year",
    "value",
    "document",
    "notes",
    "yearbook",
)


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with "
            f"`python tests/parity/capture.py {_SPEC.module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def config() -> Config:
    return load_pipeline_config(root=FIXTURES_DIR.parents[1])


@pytest.fixture(scope="module")
def file_list() -> pl.DataFrame:
    return discover_files(FIXTURES_DIR / "corpus")


@pytest.fixture(scope="module")
def sequential(config: Config, file_list: pl.DataFrame) -> ReadTransformResult:
    return read_transform_pipeline_files(
        file_list, config, options=RuntimeOptions(import_parallel_workers=1)
    )


@pytest.fixture(scope="module")
def parallel(config: Config, file_list: pl.DataFrame) -> ReadTransformResult:
    # One batch per file (batch_size=1) + several workers -> real ProcessPoolExecutor fan-out.
    small = dataclasses.replace(
        config,
        performance=dataclasses.replace(config.performance, import_workbook_batch_size=1),
    )
    return read_transform_pipeline_files(
        file_list, small, options=RuntimeOptions(import_parallel_workers=4)
    )


@pytest.mark.parity
def test_sequential_columns_and_row_count(sequential: ReadTransformResult) -> None:
    assert sequential.transformed.long_raw.columns == _gold("long_columns")
    assert str(sequential.transformed.long_raw.height) == _gold("long_nrow")[0]
    assert sequential.errors == ()


@pytest.mark.parity
@pytest.mark.parametrize("column", _VALUE_COLUMNS)
def test_sequential_column_matches_golden(column: str, sequential: ReadTransformResult) -> None:
    expected = pl.Series(column, _gold(column), dtype=pl.String)
    actual = sequential.transformed.long_raw.get_column(column)
    assert_series_equal(actual, expected, check_dtypes=True, check_names=True)


@pytest.mark.parity
def test_parallel_matches_sequential_and_golden(
    parallel: ReadTransformResult, sequential: ReadTransformResult
) -> None:
    # Determinism: parallel output is identical to sequential regardless of worker count...
    assert parallel.transformed.long_raw.equals(sequential.transformed.long_raw)
    # ...and therefore identical to the R golden.
    assert parallel.transformed.long_raw.columns == _gold("long_columns")
    for column in _VALUE_COLUMNS:
        assert parallel.transformed.long_raw.get_column(column).to_list() == _gold(column)
