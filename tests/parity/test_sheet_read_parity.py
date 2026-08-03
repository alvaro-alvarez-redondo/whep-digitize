"""Parity test: Python ``read_excel_sheet`` must match the frozen reference byte-for-byte.

Reads a real corpus workbook through the full ``read_excel_sheet`` path (all-as-text read,
``country``->``polity`` rename, base-column non-empty row filter, ``variable`` := sheet name)
and asserts every output column, the column order, and the row count match the frozen reference.
The filter is what makes this stable: blank source rows are dropped, so the surviving rows are
independent of how the underlying reader treats trailing blanks.

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_series_equal

from whep_digitize.ingest.reading.read_utils import ReadResult
from whep_digitize.ingest.reading.sheet_read import read_excel_sheet
from whep_digitize.setup.config import load_pipeline_config

_SPEC = GOLDENS["sheet_read"]
_CORPUS_REL = "corpus/fao_1949/fao_1949_crops/r_fao_1949_crops_92_92_date.xlsx"

# Golden export key -> the frame column it captured (year columns get filesystem-safe keys).
_COLUMN_EXPORTS = {
    "hemisphere": "hemisphere",
    "continent": "continent",
    "polity": "polity",
    "unit": "unit",
    "footnotes": "footnotes",
    "variable": "variable",
    "y1934_1938": "1934-1938",
    "y1946": "1946",
    "y1947": "1947",
    "y1948": "1948",
}


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def result() -> ReadResult:
    # Only column_required / column_id are consumed; root is irrelevant to the read.
    config = load_pipeline_config(root=FIXTURES_DIR.parents[1])
    return read_excel_sheet(FIXTURES_DIR / _CORPUS_REL, "production", config)


@pytest.mark.parity
def test_columns_and_row_count(result: ReadResult) -> None:
    assert result.data.columns == _gold("columns")
    assert str(result.data.height) == _gold("nrow")[0]
    assert result.errors == ()


@pytest.mark.parity
@pytest.mark.parametrize("export", sorted(_COLUMN_EXPORTS))
def test_column_matches_golden(export: str, result: ReadResult) -> None:
    column = _COLUMN_EXPORTS[export]
    expected = pl.Series(column, _gold(export), dtype=pl.String)
    actual = result.data.get_column(column)
    assert_series_equal(actual, expected, check_dtypes=True, check_names=True)
