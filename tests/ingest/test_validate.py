"""Tests for ingest output validation (``ingest.output.validate``).

Functional coverage that runs without R: each check (mandatory-field, year-value, duplicate),
the document-major reorder + per-document row ids, verbatim message formats, the plausible-year
range parameter, and error handling. Byte-for-byte R parity on the integrated multi-document
ordering lives in ``tests/parity/test_validate_parity.py``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import polars as pl
import pytest

from whep_digitize.ingest.output.validate import ValidationResult, validate_long_df_by_document
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError

# All-String frame; column_required (base) = continent, polity, unit, footnotes.
_CLEAN = {
    "continent": ["asia"],
    "polity": ["japan"],
    "unit": ["t"],
    "footnotes": ["f"],
    "year": ["1950"],
    "value": ["5"],
    "document": ["d.xlsx"],
}


def _frame(data: Mapping[str, Sequence[str | None]]) -> pl.DataFrame:
    return pl.DataFrame(dict(data), schema=dict.fromkeys(data, pl.String))


def test_clean_frame_has_no_errors(config: Config) -> None:
    result = validate_long_df_by_document(_frame(_CLEAN), config, current_year=2025)
    assert isinstance(result, ValidationResult)
    assert result.errors == ()


def test_empty_frame(config: Config) -> None:
    empty = pl.DataFrame(
        schema=dict.fromkeys(
            ("continent", "polity", "unit", "footnotes", "year", "document"), pl.String
        )
    )
    result = validate_long_df_by_document(empty, config)
    assert result.errors == ()
    assert result.data.height == 0


def test_missing_document_column_raises(config: Config) -> None:
    with pytest.raises(ValidationError, match="document"):
        validate_long_df_by_document(_frame({"year": ["1950"]}), config)


def test_empty_column_required_raises(config: Config) -> None:
    bare = dataclasses.replace(config, column_required=())
    with pytest.raises(ValidationError):
        validate_long_df_by_document(_frame(_CLEAN), bare)


# --------------------------------------------------------------------------- mandatory


def test_missing_mandatory_column_is_added_and_flagged(config: Config) -> None:
    # 'footnotes' absent entirely -> added as null -> every row flagged.
    data = {k: v for k, v in _CLEAN.items() if k != "footnotes"}
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert "footnotes" in result.data.columns
    assert result.errors == (
        "missing mandatory value in document 'd.xlsx', row_id '1', column 'footnotes'",
    )


def test_mandatory_flags_null_and_empty(config: Config) -> None:
    data: dict[str, list[str | None]] = {
        "continent": ["asia", "asia"],
        "polity": [None, ""],  # null and empty both flagged
        "unit": ["t", "t"],
        "footnotes": ["f", "f"],
        "year": ["1950", "1951"],
        "value": ["1", "2"],
        "document": ["d.xlsx", "d.xlsx"],
    }
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert result.errors == (
        "missing mandatory value in document 'd.xlsx', row_id '1', column 'polity'",
        "missing mandatory value in document 'd.xlsx', row_id '2', column 'polity'",
    )


# --------------------------------------------------------------------------- ordering


def test_document_major_reorder_and_row_ids(config: Config) -> None:
    # Interleaved documents: rows regroup document-major (b first), row_ids per document.
    data: dict[str, list[str | None]] = {
        "continent": ["asia", "europe", "asia"],
        "polity": ["japan", None, None],  # missing in the 2nd (docA) and 3rd (docB) rows
        "unit": ["t", "t", "t"],
        "footnotes": ["f", "f", "f"],
        "year": ["1950", "1951", "1952"],
        "value": ["1", "2", "3"],
        "document": ["docB", "docA", "docB"],
    }
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert result.data.get_column("document").to_list() == ["docB", "docB", "docA"]
    assert result.data.get_column("value").to_list() == ["1", "3", "2"]
    # docB's missing row is its 2nd row (row_id 2); docA's is its 1st (row_id 1). docB sorts first.
    assert result.errors == (
        "missing mandatory value in document 'docB', row_id '2', column 'polity'",
        "missing mandatory value in document 'docA', row_id '1', column 'polity'",
    )


# --------------------------------------------------------------------------- year


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        ("1899", "year value '1899' is outside plausible range [1900, 2026]"),
        ("3000", "year value '3000' is outside plausible range [1900, 2026]"),
        ("1850-1799", "year range '1850-1799' has start year greater than end year"),
    ],
)
def test_year_errors(config: Config, year: str, expected: str) -> None:
    data = {**_CLEAN, "year": [year]}
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert expected in result.errors


def test_year_range_start_after_end_and_outside(config: Config) -> None:
    # '1850-1800': start > end (key_b 1) AND start < 1900 (key_b 2) -> both, in that order.
    data = {**_CLEAN, "year": ["1850-1800"]}
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert result.errors == (
        "year range '1850-1800' has start year greater than end year",
        "year range '1850-1800' contains year outside plausible range [1900, 2026]",
    )


def test_valid_years_no_error(config: Config) -> None:
    data = {**_CLEAN, "year": ["1950-1960"]}
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert result.errors == ()


def test_current_year_controls_range(config: Config) -> None:
    data = {**_CLEAN, "year": ["2030"]}
    assert validate_long_df_by_document(_frame(data), config, current_year=2025).errors == (
        "year value '2030' is outside plausible range [1900, 2026]",
    )
    # With a later reference year 2030 becomes valid.
    assert validate_long_df_by_document(_frame(data), config, current_year=2035).errors == ()


# --------------------------------------------------------------------------- duplicate


def test_duplicate_detection_with_null_key_value(config: Config) -> None:
    data: dict[str, list[str | None]] = {
        "continent": ["asia", "asia"],
        "polity": ["japan", "japan"],
        "unit": ["t", "t"],
        "footnotes": ["f", "f"],  # non-null: avoid a mandatory error
        "notes": [None, None],  # null, non-mandatory identity key -> "notes = NA" in description
        "year": ["1950", "1950"],
        "value": ["5", "5"],
        "document": ["d.xlsx", "d.xlsx"],
    }
    result = validate_long_df_by_document(_frame(data), config, current_year=2025)
    assert result.errors == (
        "duplicate entries detected (count 2) for continent = asia, polity = japan, unit = t, "
        "year = 1950, value = 5, notes = NA, footnotes = f, document = d.xlsx",
    )
