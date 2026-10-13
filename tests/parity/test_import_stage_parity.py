"""Stage-level parity: ``run_ingest_pipeline`` output must match the frozen reference exactly.

Runs the full ingest stage over the frozen corpus and asserts the consolidated, canonically
sorted long frame (every column) and the reading / validation / consolidation diagnostics all
equal the frozen reference. ``current_year`` is pinned to 2025 to match the
capture's ``Sys.Date`` override (the corpus has no out-of-range years, so this only guards
determinism).

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import dataclasses
import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS, current_message, current_names, legacy_key
from polars.testing import assert_series_equal

from whep_digitize.contracts import InputResult
from whep_digitize.ingest.runner import run_ingest_pipeline
from whep_digitize.setup.config import load_pipeline_config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.sorting import sort_pipeline_stage_df

_SPEC = GOLDENS["import_stage"]
_PINNED_YEAR = 2025
# Columns the pipeline added after the goldens were frozen. The goldens are immutable, so they
# know nothing about these: the golden comparison is made over the columns they do cover, and
# each added column is pinned separately below.
_ADDED_COLUMNS = ("iso_whep",)
# ``iso_whep`` is also a sort key (between continent and polity), and it is seeded from ``year``,
# so it reorders rows. The goldens hold the order of the key without it; the value comparison
# re-sorts by that key, which reproduces the golden order exactly (rows tied on all of it are
# identical, iso_whep included, since iso_whep is derived from year).
_GOLDEN_SORT_KEY = tuple(
    column
    for column in get_pipeline_constants().sorting.stage_row_order
    if column not in _ADDED_COLUMNS
)
_DATA_COLUMNS = (
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "value",
    "notes",
    "footnotes",
    "yearbook",
    "file",
)


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[legacy_key(name)]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def result() -> InputResult:
    corpus = FIXTURES_DIR / "corpus"
    base = load_pipeline_config(root=FIXTURES_DIR.parents[1])
    input_paths = dataclasses.replace(base.paths.data.input, raw=corpus)
    data_paths = dataclasses.replace(base.paths.data, input=input_paths)
    config = dataclasses.replace(base, paths=dataclasses.replace(base.paths, data=data_paths))
    return run_ingest_pipeline(config, current_year=_PINNED_YEAR)


@pytest.mark.parity
def test_data_columns_and_row_count(result: InputResult) -> None:
    golden_columns = [name for name in result.data.columns if name not in _ADDED_COLUMNS]
    assert golden_columns == current_names(_gold("data_columns"))
    assert str(result.data.height) == _gold("data_nrow")[0]


@pytest.mark.parity
def test_iso_whep_is_seeded_from_year_and_ordered(result: InputResult) -> None:
    """``iso_whep`` is created as ``"iso-" + year``, between ``continent`` and ``polity``.

    No source workbook carries it, so ingest creates it for every row, seeded once from the
    row's own year; clean/harmonize rules rewrite it later.
    """
    data = result.data
    columns = data.columns
    position = columns.index("iso_whep")
    assert columns.index("continent") + 1 == position == columns.index("polity") - 1
    expected = pl.concat_str(pl.lit("iso-"), pl.col("year"))
    assert data.select((pl.col("iso_whep") == expected).all()).item()


@pytest.mark.parity
def test_rows_follow_the_sort_key_including_iso_whep(result: InputResult) -> None:
    # The produced order is the current key (iso_whep before polity), not the golden's.
    assert result.data.equals(sort_pipeline_stage_df(result.data))


@pytest.mark.parity
@pytest.mark.parametrize("column", _DATA_COLUMNS)
def test_data_column_matches_golden(column: str, result: InputResult) -> None:
    expected = pl.Series(column, _gold(column), dtype=pl.String)
    in_golden_order = sort_pipeline_stage_df(result.data, _GOLDEN_SORT_KEY)
    assert_series_equal(
        in_golden_order.get_column(column), expected, check_dtypes=True, check_names=True
    )


@pytest.mark.parity
def test_diagnostics_match_golden(result: InputResult) -> None:
    assert list(result.diagnostics.reading_errors) == _gold("reading_errors")
    assert list(result.diagnostics.validation_errors) == [
        current_message(message) for message in _gold("validation_errors")
    ]
    assert list(result.diagnostics.warnings) == _gold("warnings")
