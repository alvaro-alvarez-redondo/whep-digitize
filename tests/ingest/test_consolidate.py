"""Tests for ingest output consolidation (``ingest.assemble.consolidate``)."""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

from whep_digitize.ingest.assemble.consolidate import (
    consolidate_audited_df,
    validate_column_order,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError

# --------------------------------------------------------------------------- column order


def test_validate_output_column_order_ok(config: Config) -> None:
    assert validate_column_order(config) == list(config.column_order)


def test_validate_output_column_order_duplicate(config: Config) -> None:
    bad = dataclasses.replace(config, column_order=(*config.column_order, "year"))
    with pytest.raises(ValidationError, match="unique"):
        validate_column_order(bad)


def test_validate_output_column_order_missing_schema(config: Config) -> None:
    bad = dataclasses.replace(config, column_order=("year", "value", "file"))
    with pytest.raises(ValidationError, match="target schema"):
        validate_column_order(bad)


# --------------------------------------------------------------------------- consolidate


def test_consolidate_reorders_and_fills_missing(config: Config) -> None:
    # Arbitrary column order + an extra column, several schema columns absent.
    frame = pl.DataFrame({"value": ["5"], "file": ["d"], "continent": ["asia"], "extra": ["x"]})
    result = consolidate_audited_df([frame], config)
    assert result.data.columns == [*config.column_order, "extra"]  # canonical first, extra last
    assert result.data["value"].to_list() == ["5"]
    assert result.data["hemisphere"].to_list() == [None]  # missing schema column -> null
    assert result.data.schema["hemisphere"] == pl.String
    assert result.warnings == ()


def test_consolidate_skips_none_and_concats(config: Config) -> None:
    first = pl.DataFrame({"continent": ["asia"], "value": ["1"], "file": ["a"]})
    second = pl.DataFrame({"continent": ["europe"], "value": ["2"], "file": ["b"]})
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


def test_validate_output_column_order_requires_iso_whep(config: Config) -> None:
    # Every other schema column present, only the new one omitted: still rejected.
    bad = dataclasses.replace(
        config, column_order=tuple(c for c in config.column_order if c != "iso_whep")
    )
    with pytest.raises(ValidationError, match="iso_whep"):
        validate_column_order(bad)


def test_consolidate_seeds_iso_whep_from_year_between_continent_and_polity(
    config: Config,
) -> None:
    # Two source files, combined first: the column is created once, over the whole raw frame.
    first = pl.DataFrame(
        {"continent": ["asia"], "polity": ["japan"], "year": ["1937"], "value": ["1"]}
    )
    second = pl.DataFrame(
        {"continent": ["europe"], "polity": ["spain"], "year": ["1934-1939"], "value": ["2"]}
    )

    data = consolidate_audited_df([first, second], config).data

    assert data["iso_whep"].to_list() == ["iso-1937", "iso-1934-1939"]
    assert data.schema["iso_whep"] == pl.String
    columns = data.columns
    position = columns.index("iso_whep")
    assert columns.index("continent") + 1 == position == columns.index("polity") - 1


def test_consolidate_seeds_null_iso_whep_where_year_is_missing(config: Config) -> None:
    frame = pl.DataFrame(
        {"polity": ["japan", "spain"], "year": ["1950", None], "value": ["1", "2"]}
    )

    data = consolidate_audited_df([frame], config).data

    assert data["iso_whep"].to_list() == ["iso-1950", None]
