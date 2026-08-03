"""Parity test: Python ``transform_file_df`` must match the R golden long shape byte-for-byte.

Reads a real corpus sheet, runs the full per-file transform (key-field normalization,
year-header cleanup, wide->long melt, metadata enrichment, null-value drop), and asserts the
long frame's column order, row count, and every column value match R's ``data.table::melt``
based output. This is the check that ``pl.DataFrame.unpivot`` drops exactly the columns
``melt`` did and produces the same variable-major row order (parity risk #2).

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_series_equal

from whep_digitize.ingest.reading.sheet_read import read_excel_sheet
from whep_digitize.ingest.transform.reshape import TransformResult, transform_file_df
from whep_digitize.setup.config import load_pipeline_config

_SPEC = GOLDENS["transform"]
_CORPUS_REL = "corpus/fao_1949/fao_1949_crops/r_fao_1949_crops_92_92_date.xlsx"

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
def result() -> TransformResult:
    config = load_pipeline_config(root=FIXTURES_DIR.parents[1])
    wide = read_excel_sheet(FIXTURES_DIR / _CORPUS_REL, "production", config).data
    return transform_file_df(wide, "r_fao_1949_crops_92_92_date.xlsx", "fao_1949", "date", config)


@pytest.mark.parity
def test_long_columns_and_row_count(result: TransformResult) -> None:
    assert result.long_raw.columns == _gold("long_columns")
    assert str(result.long_raw.height) == _gold("long_nrow")[0]


@pytest.mark.parity
@pytest.mark.parametrize("column", _VALUE_COLUMNS)
def test_long_column_matches_golden(column: str, result: TransformResult) -> None:
    expected = pl.Series(column, _gold(column), dtype=pl.String)
    actual = result.long_raw.get_column(column)
    assert_series_equal(actual, expected, check_dtypes=True, check_names=True)
