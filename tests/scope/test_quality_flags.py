"""Smoke tests for scope quality flags."""

from __future__ import annotations

import pandas as pd

from scope.quality_flags import flag_aggregate_rows, flag_value_outliers


def test_flag_aggregate_rows_marks_total_and_bare_polities() -> None:
    """Aggregate rollups should be identified by substring and bare region names."""
    frame = pd.DataFrame(
        {
            "polity": ["France", "World Total", "asia", "Total Africa", "Kenya"],
        }
    )

    flagged = flag_aggregate_rows(frame)

    assert flagged["is_aggregate"].tolist() == [False, True, True, True, False]


def test_flag_value_outliers_vectorized_basic() -> None:
    """Vectorized outlier detection should identify outliers correctly."""
    # Create data with clear outlier in one group
    frame = pd.DataFrame({
        "unit": ["tons", "tons", "tons", "tons", "tons", "tons", "tons", "tons", "tons", "tons"],
        "variable": ["production"] * 10,
        "value": [10.0, 11.0, 10.5, 10.2, 10.8, 10.3, 10.7, 10.1, 10.9, 1000.0],  # 1000 is outlier
    })

    result = flag_value_outliers(frame)

    # The last value (1000.0) should be flagged as outlier
    assert result.loc[9, "value_is_outlier"] == True  # noqa: E712
    # All others should not be outliers
    assert result.loc[0:8, "value_is_outlier"].sum() == 0


def test_flag_value_outliers_vectorized_small_group() -> None:
    """Small groups below minimum_group_size should not have outlier detection."""
    frame = pd.DataFrame({
        "unit": ["tons"] * 5,
        "variable": ["production"] * 5,
        "value": [10.0, 11.0, 1000.0, 10.5, 10.2],  # Would be outlier but group too small
    })

    result = flag_value_outliers(frame, minimum_group_size=8)

    # All should be False because group size < 8
    assert result["value_is_outlier"].sum() == 0


def test_flag_value_outliers_vectorized_multiple_groups() -> None:
    """Vectorized outlier detection should handle multiple groups independently."""
    frame = pd.DataFrame({
        "unit": ["tons"] * 10 + ["kg"] * 10,
        "variable": ["production"] * 20,
        "value": [10.0, 11.0, 10.5, 10.2, 10.8, 10.3, 10.7, 10.1, 10.9, 1000.0,  # outlier in tons
                  1.0, 1.1, 1.05, 1.02, 1.08, 1.03, 1.07, 1.01, 1.09, 100.0],    # outlier in kg
    })

    result = flag_value_outliers(frame, minimum_group_size=8)

    # Both outliers should be detected (indices 9 and 19)
    assert result.loc[9, "value_is_outlier"] == True  # noqa: E712
    assert result.loc[19, "value_is_outlier"] == True  # noqa: E712
    # Non-outliers should be False
    total_outliers = result["value_is_outlier"].sum()
    assert total_outliers == 2
