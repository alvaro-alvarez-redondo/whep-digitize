"""Tests for ingest output consolidation (``ingest.output.consolidate``)."""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

from whep_digitize.ingest.output.consolidate import (
    consolidate_audited_df,
    validate_output_column_order,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError

# --------------------------------------------------------------------------- column order


def test_validate_output_column_order_ok(config: Config) -> None:
    assert validate_output_column_order(config) == list(config.column_order)


def test_validate_output_column_order_duplicate(config: Config) -> None:
    bad = dataclasses.replace(config, column_order=(*config.column_order, "year"))
    with pytest.raises(ValidationError, match="unique"):
        validate_output_column_order(bad)


def test_validate_output_column_order_missing_schema(config: Config) -> None:
    bad = dataclasses.replace(config, column_order=("year", "value", "document"))
    with pytest.raises(ValidationError, match="target schema"):
        validate_output_column_order(bad)


# --------------------------------------------------------------------------- consolidate


def test_consolidate_reorders_and_fills_missing(config: Config) -> None:
    # Arbitrary column order + an extra column, several schema columns absent.
    frame = pl.DataFrame({"value": ["5"], "document": ["d"], "continent": ["asia"], "extra": ["x"]})
    result = consolidate_audited_df([frame], config)
    assert result.data.columns == [*config.column_order, "extra"]  # canonical first, extra last
    assert result.data["value"].to_list() == ["5"]
    assert result.data["hemisphere"].to_list() == [None]  # missing schema column -> null
    assert result.data.schema["hemisphere"] == pl.String
    assert result.warnings == ()


def test_consolidate_skips_none_and_concats(config: Config) -> None:
    first = pl.DataFrame({"continent": ["asia"], "value": ["1"], "document": ["a"]})
    second = pl.DataFrame({"continent": ["europe"], "value": ["2"], "document": ["b"]})
    result = consolidate_audited_df([first, None, second], config)
    assert result.data.height == 2
    assert result.data["continent"].to_list() == ["asia", "europe"]
    assert result.warnings == ()


def test_consolidate_empty_list_warns(config: Config) -> None:
    with pytest.warns(UserWarning, match="no data tables were provided"):
        result = consolidate_audited_df([], config)
    assert result.data.height == 0
    assert result.warnings == ("no data tables were provided for consolidation",)


def test_consolidate_all_none_warns(config: Config) -> None:
    with pytest.warns(UserWarning, match="no data tables were provided"):
        result = consolidate_audited_df([None, None], config)
    assert result.warnings == ("no data tables were provided for consolidation",)
