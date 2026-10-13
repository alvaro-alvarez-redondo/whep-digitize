"""Smoke tests for scope transformers."""

from __future__ import annotations

import pandas as pd

from scope.transformers import add_year_columns, parse_year_value


def test_parse_year_value_handles_single_year() -> None:
    """A single year should map to identical start/end values."""
    result = parse_year_value("1930")
    assert result.year_start == 1930
    assert result.year_end == 1930
    assert result.is_period_range is False
    assert result.decade == 1930


def test_parse_year_value_handles_year_range() -> None:
    """A hyphenated period should map to explicit start/end bounds."""
    result = parse_year_value("1925-1929")
    assert result.year_start == 1925
    assert result.year_end == 1929
    assert result.is_period_range is True
    assert result.decade == 1920


def test_parse_year_value_rejects_bad_input() -> None:
    """Malformed year strings should fail closed with null outputs."""
    result = parse_year_value("not-a-year")
    assert result.year_start is None
    assert result.year_end is None
    assert result.is_period_range is False
    assert result.decade is None


def test_add_year_columns_vectorized_single_years() -> None:
    """Vectorized year parsing should handle single years correctly."""
    frame = pd.DataFrame({
        "year": ["1930", "1945", "1950", None, "invalid"],
    })
    result = add_year_columns(frame)

    assert result.loc[0, "year_start"] == 1930
    assert result.loc[0, "year_end"] == 1930
    assert result.loc[0, "is_period_range"] == False  # noqa: E712
    assert result.loc[0, "decade"] == 1930

    assert result.loc[1, "year_start"] == 1945
    assert result.loc[2, "year_start"] == 1950

    # None and invalid should have NA
    assert pd.isna(result.loc[3, "year_start"])
    assert pd.isna(result.loc[4, "year_start"])


def test_add_year_columns_vectorized_year_ranges() -> None:
    """Vectorized year parsing should handle year ranges correctly."""
    frame = pd.DataFrame({
        "year": ["1925-1929", "1930-1935", "1940 - 1945"],  # with spaces too
    })
    result = add_year_columns(frame)

    assert result.loc[0, "year_start"] == 1925
    assert result.loc[0, "year_end"] == 1929
    assert result.loc[0, "is_period_range"] == True  # noqa: E712
    assert result.loc[0, "decade"] == 1920

    assert result.loc[1, "year_start"] == 1930
    assert result.loc[1, "year_end"] == 1935

    # With spaces around hyphen parts
    assert result.loc[2, "year_start"] == 1940
    assert result.loc[2, "year_end"] == 1945


def test_add_year_columns_vectorized_mixed() -> None:
    """Vectorized year parsing should handle mixed single and range years."""
    frame = pd.DataFrame({
        "year": ["1930", "1925-1929", "1950", "1940-1945"],
    })
    result = add_year_columns(frame)

    # Single years
    assert result.loc[0, "is_period_range"] == False  # noqa: E712
    assert result.loc[2, "is_period_range"] == False  # noqa: E712

    # Ranges
    assert result.loc[1, "is_period_range"] == True  # noqa: E712
    assert result.loc[3, "is_period_range"] == True  # noqa: E712
