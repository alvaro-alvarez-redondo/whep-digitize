"""Parity test: Python file-metadata extraction must match the frozen reference byte-for-byte.

Reads the per-column goldens and asserts
:func:`whep_digitize.ingest.file_io.metadata.extract_file_metadata` reproduces each output column
over the frozen file-name fixture (real WHEP corpus paths plus edge cases: no year token,
<2 tokens, first-year-wins, non-ASCII).

Each column is compared in the goldens' string form (null -> ``None``), matching how they were
serialized; the boolean ``is_ascii`` maps to ``"TRUE"`` / ``"FALSE"``. Goldens
are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_series_equal

from whep_digitize.ingest.file_io.metadata import extract_file_metadata

_SPEC = GOLDENS["file_metadata"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME


def _load_json(path: Path) -> list[str | None]:
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _as_golden_text(frame: pl.DataFrame, column: str) -> pl.Series:
    """Render one metadata column to the goldens' string form for comparison."""
    series = frame.get_column(column)
    if series.dtype == pl.Boolean:
        # The goldens spell booleans "TRUE"/"FALSE"; polars casts to "true", so map explicitly.
        # is_ascii is never null, so the null branch need not be modelled here.
        return frame.select(
            pl.when(pl.col(column)).then(pl.lit("TRUE")).otherwise(pl.lit("FALSE")).alias(column)
        ).get_column(column)
    return series.cast(pl.String)


@pytest.fixture(scope="module")
def result() -> pl.DataFrame:
    """The Python metadata frame over the frozen file-name fixture."""
    inputs = _load_json(_FIXTURE_PATH)
    return extract_file_metadata([path for path in inputs if path is not None])


@pytest.mark.parity
@pytest.mark.parametrize("export", sorted(_SPEC.exports))
def test_matches_golden(export: str, result: pl.DataFrame) -> None:
    golden_path = _SPEC.golden_paths()[export]
    if not golden_path.is_file():
        pytest.skip(
            f"Golden {golden_path} is missing from the checkout; restore it from version "
            "control (the goldens are frozen and have no regeneration path)."
        )
    expected = pl.Series(export, _load_json(golden_path), dtype=pl.String)
    actual = _as_golden_text(result, export).rename(export)
    assert_series_equal(actual, expected, check_dtypes=True, check_names=True)
