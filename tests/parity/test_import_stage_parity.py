"""Stage-level parity: ``run_import_pipeline`` output must match the frozen reference exactly.

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
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_series_equal

from whep_digitize.contracts import ImportResult
from whep_digitize.ingest.runner import run_import_pipeline
from whep_digitize.setup.config import load_pipeline_config

_SPEC = GOLDENS["import_stage"]
_PINNED_YEAR = 2025
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
    "document",
)


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
def result() -> ImportResult:
    corpus = FIXTURES_DIR / "corpus"
    base = load_pipeline_config(root=FIXTURES_DIR.parents[1])
    import_ = dataclasses.replace(base.paths.data.import_, raw=corpus)
    data_paths = dataclasses.replace(base.paths.data, import_=import_)
    config = dataclasses.replace(base, paths=dataclasses.replace(base.paths, data=data_paths))
    return run_import_pipeline(config, current_year=_PINNED_YEAR)


@pytest.mark.parity
def test_data_columns_and_row_count(result: ImportResult) -> None:
    assert result.data.columns == _gold("data_columns")
    assert str(result.data.height) == _gold("data_nrow")[0]


@pytest.mark.parity
@pytest.mark.parametrize("column", _DATA_COLUMNS)
def test_data_column_matches_golden(column: str, result: ImportResult) -> None:
    expected = pl.Series(column, _gold(column), dtype=pl.String)
    assert_series_equal(
        result.data.get_column(column), expected, check_dtypes=True, check_names=True
    )


@pytest.mark.parity
def test_diagnostics_match_golden(result: ImportResult) -> None:
    assert list(result.diagnostics.reading_errors) == _gold("reading_errors")
    assert list(result.diagnostics.validation_errors) == _gold("validation_errors")
    assert list(result.diagnostics.warnings) == _gold("warnings")
