"""Tests for ingest transform: transform_utils + reshape.

Functional coverage that runs without R: year-column identification, key-field
normalization, year-header cleanup + collision guard, the wide->long melt (including the
column-drop behaviour), metadata enrichment, the per-file transform, and commodity
resolution. Byte-for-byte R parity on the long shape lives in
``tests/parity/test_transform_parity.py``.
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

from whep_digitize.ingest.transform.reshape import (
    TransformResult,
    add_metadata,
    build_empty_transform_result,
    reshape_to_long,
    resolve_commodity_name,
    transform_file_df,
)
from whep_digitize.ingest.transform.transform_utils import (
    convert_year_columns,
    identify_year_columns,
    normalize_key_fields,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.options import RuntimeOptions

# --------------------------------------------------------------------------- identify_year_columns


def test_identify_year_columns(config: Config) -> None:
    frame = pl.DataFrame(
        {"continent": ["x"], "2020": ["1"], "1990-1994": ["2"], "notes": ["n"], "random": ["r"]}
    )
    assert identify_year_columns(frame, config) == ["2020", "1990-1994"]


def test_identify_year_columns_empty(config: Config) -> None:
    assert identify_year_columns(pl.DataFrame(), config) == []


def test_identify_year_columns_excludes_metadata(config: Config) -> None:
    # A metadata column is excluded even if nothing else qualifies.
    frame = pl.DataFrame({"continent": ["x"], "polity": ["y"]})
    assert identify_year_columns(frame, config) == []


# --------------------------------------------------------------------------- normalize_key_fields


def test_normalize_key_fields(config: Config) -> None:
    frame = pl.DataFrame(
        {
            "continent": ["Europe", None],
            "polity": ["Spain", "España"],
            "unit": ["Tonnes", "Tonnes"],
            "footnotes": ["See (a)", None],
            "variable": ["Production", "Production"],
            "1950": ["1", "2"],
        }
    )
    result = normalize_key_fields(frame, "Wheat", config)
    assert result["commodity"].to_list() == ["wheat", "wheat"]  # scalar, normalized
    assert result["continent"].to_list() == ["europe", None]
    assert result["polity"].to_list() == ["spain", "espana"]  # accents folded
    assert result["variable"].to_list() == ["production", "production"]
    assert result["unit"].to_list() == ["Tonnes", "Tonnes"]  # unit left raw
    assert result["footnotes"].to_list() == ["see (a)", None]  # cleaned, punctuation kept


def test_normalize_key_fields_adds_missing_base(config: Config) -> None:
    frame = pl.DataFrame({"continent": ["x"], "polity": ["y"], "unit": ["u"], "2000": ["1"]})
    result = normalize_key_fields(frame, "wheat", config)
    assert "footnotes" in result.columns  # missing base column added
    assert result["footnotes"].null_count() == result.height
    assert result.schema["footnotes"] == pl.String


# --------------------------------------------------------------------------- convert_year_columns


def test_convert_year_columns_cleanups(config: Config) -> None:
    frame = pl.DataFrame(
        {"continent": ["x"], "2020.0": ["1"], "2019-20": ["2"], "2018-19/2019-20": ["3"]}
    )
    result = convert_year_columns(frame, config)
    assert result.columns == ["continent", "2020", "2019", "2018-2019"]


def test_convert_year_columns_collision_aborts(config: Config) -> None:
    # calendar "2020" and crop-year "2020-21" both clean to "2020" -> fatal.
    frame = pl.DataFrame({"2020": ["1"], "2020-21": ["2"]})
    with pytest.raises(ValidationError, match="duplicate column names"):
        convert_year_columns(frame, config)


def test_convert_year_columns_no_change(config: Config) -> None:
    frame = pl.DataFrame({"continent": ["x"], "2020": ["1"]})
    result = convert_year_columns(frame, config)
    assert result.columns == ["continent", "2020"]


# --------------------------------------------------------------------------- reshape_to_long


def test_reshape_to_long_drops_non_id_non_year(config: Config) -> None:
    # 'extra' is neither an id column nor a year column -> dropped (like R melt).
    frame = pl.DataFrame({"continent": ["eu", "as"], "extra": ["p", "q"], "2020": ["1", "2"]})
    long = reshape_to_long(frame, config)
    assert long.columns == ["continent", "year", "value"]
    assert "extra" not in long.columns
    assert long["year"].to_list() == ["2020", "2020"]
    assert long["value"].to_list() == ["1", "2"]


def test_reshape_to_long_no_year_columns(config: Config) -> None:
    with pytest.raises(ValidationError, match="no year columns"):
        reshape_to_long(pl.DataFrame({"continent": ["x"], "polity": ["y"]}), config)


def test_reshape_to_long_variable_major_order(config: Config) -> None:
    frame = pl.DataFrame({"continent": ["a", "b"], "2019": ["1", "2"], "2020": ["3", "4"]})
    long = reshape_to_long(frame, config)
    # data.table melt / polars unpivot stack measures: all rows of 2019, then all of 2020.
    assert long["year"].to_list() == ["2019", "2019", "2020", "2020"]
    assert long["value"].to_list() == ["1", "2", "3", "4"]


# --------------------------------------------------------------------------- add_metadata


def test_add_metadata(config: Config) -> None:
    long = pl.DataFrame({"continent": ["x"], "year": ["2020"], "value": ["1"]})
    result = add_metadata(long, "file.xlsx", "fao_2020", config)
    assert result.columns == ["continent", "year", "value", "document", "notes", "yearbook"]
    assert result["document"].to_list() == ["file.xlsx"]
    assert result["yearbook"].to_list() == ["fao_2020"]
    assert result["notes"].to_list() == [None]  # config default notes_value is None
    assert result.schema["notes"] == pl.String


# --------------------------------------------------------------------------- transform_file_df


def _wide() -> pl.DataFrame:
    # Mirrors a read sheet's output: base cols + hemisphere + variable (sheet name) + years.
    return pl.DataFrame(
        {
            "continent": ["europe", "asia"],
            "polity": ["spain", "japan"],
            "unit": ["t", "t"],
            "footnotes": [None, None],
            "hemisphere": ["north", "north"],
            "variable": ["production", "production"],
            "2019": ["10", None],
            "2020": ["20", "30"],
        },
        schema_overrides={"footnotes": pl.String},
    )


def test_transform_file_df(config: Config) -> None:
    result = transform_file_df(_wide(), "f.xlsx", "fao_2020", "wheat", config)
    assert isinstance(result, TransformResult)
    assert result.long_raw.columns == [
        "commodity",
        "variable",
        "unit",
        "hemisphere",
        "continent",
        "polity",
        "footnotes",
        "year",
        "value",
        "document",
        "notes",
        "yearbook",
    ]
    # 2 rows x 2 years = 4, minus the one null value (2019/asia) -> 3.
    assert result.long_raw.height == 3
    assert result.long_raw["commodity"].unique().to_list() == ["wheat"]
    assert result.wide_raw["commodity"].unique().to_list() == ["wheat"]  # appended, normalized


def test_transform_file_df_keeps_nulls_when_disabled(config: Config) -> None:
    options = RuntimeOptions(drop_na_values=False)
    result = transform_file_df(_wide(), "f.xlsx", "fao_2020", "wheat", config, options)
    assert result.long_raw.height == 4  # no null-value drop


def test_transform_file_df_blank_args(config: Config) -> None:
    with pytest.raises(ValidationError):
        transform_file_df(_wide(), "", "fao_2020", "wheat", config)


# --------------------------------------------------------------------------- resolve_commodity_name


@pytest.mark.parametrize(
    ("commodity", "expected"),
    [
        ("wheat", "wheat"),
        ("  wheat  ", "wheat"),
        (None, "(unknown_commodity)"),
        ("", "(unknown_commodity)"),
        ("   ", "(unknown_commodity)"),
    ],
)
def test_resolve_commodity_name(config: Config, commodity: str | None, expected: str) -> None:
    assert resolve_commodity_name(commodity, config) == expected


def test_resolve_commodity_name_warns_when_enabled(config: Config) -> None:
    warning_config = dataclasses.replace(config, show_missing_commodity_metadata_warning=True)
    with pytest.warns(UserWarning, match="missing commodity metadata"):
        result = resolve_commodity_name(None, warning_config, file_name="f.xlsx")
    assert result == "(unknown_commodity)"


def test_build_empty_transform_result() -> None:
    result = build_empty_transform_result()
    assert result.wide_raw.height == 0
    assert result.long_raw.height == 0
