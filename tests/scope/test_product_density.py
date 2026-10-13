"""Smoke tests for product data-point density charts."""

from __future__ import annotations

import pandas as pd

from scope.config import build_config
from scope.visualizations import (
    build_product_data_point_density_figure,
    build_product_data_point_density_figures,
)


def test_product_density_figure_zero_fills_missing_years() -> None:
    """Each commodity series should be reindexed across the full year range."""
    frame = pd.DataFrame(
        {
            "variable": ["production", "production", "production"],
            "commodity": ["wheat", "wheat", "corn"],
            "year_start": [1930, 1932, 1931],
            "is_aggregate": [False, False, False],
        }
    )
    config = build_config()

    figure = build_product_data_point_density_figure(frame, config, "production")

    assert len(figure.data) == 2
    assert list(figure.data[0].x) == [1930, 1931, 1932]
    assert list(figure.data[0].y) == [1, 0, 1]


def test_product_density_figures_respect_skip_thin_variables() -> None:
    """Sparse variables should be skipped when the flag is enabled."""
    frame = pd.DataFrame(
        {
            "variable": ["production"],
            "commodity": ["wheat"],
            "year_start": [1930],
            "is_aggregate": [False],
        }
    )
    config = build_config()

    figures = build_product_data_point_density_figures(
        frame,
        config,
        skip_thin_variables=True,
    )

    assert figures == {}
