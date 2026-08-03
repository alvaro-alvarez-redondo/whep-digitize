"""Tests for the processed-data export (``export.processed_data``).

(layer detection, path
naming, the TSV writer, and the harmonize-by-default filter) and adds focused coverage of the
the fixed-notation float rendering that the byte-parity test depends on.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import polars as pl
import pytest

from whep_digitize.export.processed_data.export import (
    _FWRITE_EOL,
    build_processed_export_path,
    export_processed_data,
    write_processed_table,
)
from whep_digitize.export.processed_data.layers import collect_layer_tables_for_export
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.numeric import format_double_r


def _frame() -> pl.DataFrame:
    return pl.DataFrame({"polity": ["a", "b"], "value": ["1", "2"]})


# --------------------------------------------------------------------------- layer detection


def test_collect_auto_detects_supported_layers() -> None:
    objects = {
        "demo_raw": _frame(),
        "demo_clean": _frame(),
        "demo_other": _frame(),
        "demo_wide_raw": _frame(),
    }
    detected = collect_layer_tables_for_export(objects)
    assert set(detected) == {"demo_clean", "demo_raw"}
    assert "demo_wide_raw" not in detected
    assert "demo_other" not in detected


def test_collect_rejects_unsupported_suffixes() -> None:
    objects = {
        "whep_data_clean": _frame(),
        "whep_data_harmonize": _frame(),
        "whep_data_standardize": _frame(),
    }
    detected = collect_layer_tables_for_export(objects)
    assert set(detected) == {"whep_data_clean", "whep_data_harmonize"}
    assert "whep_data_standardize" not in detected


def test_collect_drops_post_processed_and_wide_raw() -> None:
    objects = {
        "whep_data_raw": _frame(),
        "whep_data_clean": _frame(),
        "whep_data_harmonize": _frame(),
        "whep_data_standardize": _frame(),
        "whep_data_post_processed": _frame(),
        "whep_data_wide_raw": _frame(),
    }
    detected = collect_layer_tables_for_export(objects)
    assert set(detected) == {"whep_data_clean", "whep_data_harmonize", "whep_data_raw"}


def test_collect_orders_by_name() -> None:
    objects = {"z_raw": _frame(), "a_harmonize": _frame(), "m_clean": _frame()}
    assert list(collect_layer_tables_for_export(objects)) == ["a_harmonize", "m_clean", "z_raw"]


def test_collect_accepts_explicit_objects() -> None:
    detected = collect_layer_tables_for_export({"test_raw": _frame(), "test_clean": _frame()})
    assert set(detected) == {"test_raw", "test_clean"}


def test_collect_empty_raises() -> None:
    with pytest.raises(ValidationError, match="no layer tables detected"):
        collect_layer_tables_for_export({"demo_other": _frame(), "x_wide_raw": _frame()})


def test_collect_rejects_empty_suffixes() -> None:
    with pytest.raises(ValidationError, match="at least one suffix"):
        collect_layer_tables_for_export({"a_raw": _frame()}, layer_suffixes=())


def test_collect_rejects_duplicate_suffixes() -> None:
    with pytest.raises(ValidationError, match="unique"):
        collect_layer_tables_for_export({"a_raw": _frame()}, layer_suffixes=("raw", "raw"))


def test_collect_ignores_blank_name() -> None:
    detected = collect_layer_tables_for_export({"": _frame(), "a_raw": _frame()})
    assert list(detected) == ["a_raw"]


# --------------------------------------------------------------------------- path build


def test_build_path_naming(config: Config) -> None:
    path = build_processed_export_path(config, "dataset_harmonize")
    assert path.name == "dataset_harmonize.tsv"
    assert path.parent == config.paths.data.export.processed


def test_build_path_normalizes_name(config: Config) -> None:
    path = build_processed_export_path(config, "Food Balance Sheet")
    assert path.name == "food_balance_sheet.tsv"


def test_build_path_empty_name_raises(config: Config) -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        build_processed_export_path(config, "")


# --------------------------------------------------------------------------- writer


def test_write_round_trips(tmp_path: Path) -> None:
    frame = pl.DataFrame({"polity": ["Japan", "France"], "value": ["100", "200"]})
    out = write_processed_table(frame, tmp_path / "output.tsv")
    assert out.is_file()
    read_back = pl.read_csv(out, separator="\t", infer_schema_length=0)
    assert read_back.columns == ["polity", "value"]
    assert read_back["polity"].to_list() == ["Japan", "France"]


def test_write_uses_platform_eol(tmp_path: Path) -> None:
    out = write_processed_table(pl.DataFrame({"a": ["1"]}), tmp_path / "o.tsv")
    assert out.read_bytes() == f"a{_FWRITE_EOL}1{_FWRITE_EOL}".encode()


def test_write_renders_floats_in_fixed_notation(tmp_path: Path) -> None:
    frame = pl.DataFrame({"value": [1.0, 2.5, 1000.0, None, -3.5]}, schema={"value": pl.Float64})
    out = write_processed_table(frame, tmp_path / "f.tsv")
    # read_bytes (not read_text) so the CRLF terminators survive universal-newline translation.
    text = out.read_bytes().decode("utf-8")
    assert text.split(_FWRITE_EOL) == ["value", "1", "2.5", "1000", "", "-3.5", ""]


def test_write_respects_overwrite_flag(tmp_path: Path) -> None:
    path = tmp_path / "output.tsv"
    write_processed_table(_frame(), path)
    with pytest.raises(ValidationError, match="overwrite"):
        write_processed_table(_frame(), path, overwrite=False)


def test_write_overwrites_by_default(tmp_path: Path) -> None:
    path = tmp_path / "output.tsv"
    write_processed_table(pl.DataFrame({"a": ["1"]}), path)
    write_processed_table(pl.DataFrame({"a": ["2"]}), path)  # no error
    assert pl.read_csv(path, separator="\t", infer_schema_length=0)["a"].to_list() == ["2"]


# --------------------------------------------------------------------------- float formatting


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "1"),
        (-1.0, "-1"),
        (1000.0, "1000"),
        (100000.0, "100000"),
        (999999999999.0, "999999999999"),
        (0.0, "0"),
        (-0.0, "0"),
        (2.5, "2.5"),
        (-3.5, "-3.5"),
        (0.1, "0.1"),
        (12.34, "12.34"),
        (830447.6, "830447.6"),
    ],
)
def test_format_double_r(value: float, expected: str) -> None:
    assert format_double_r(value) == expected


def test_format_double_r_special() -> None:
    assert format_double_r(float("nan")) is None
    assert format_double_r(float("inf")) == "Inf"
    assert format_double_r(float("-inf")) == "-Inf"


# --------------------------------------------------------------------------- orchestration


def _export_objects() -> dict[str, pl.DataFrame]:
    frame = pl.DataFrame({"polity": ["a", "b"], "value": ["1", "2"]})
    return {"test_raw": frame, "test_clean": frame, "test_harmonize": frame}


def test_export_writes_harmonize_only_by_default(config: Config) -> None:
    config.paths.data.export.processed.mkdir(parents=True, exist_ok=True)
    paths = export_processed_data(config, _export_objects())
    assert list(paths) == ["test_harmonize"]
    assert paths["test_harmonize"].is_file()


def test_export_honors_config_export_layers(config: Config) -> None:
    config.paths.data.export.processed.mkdir(parents=True, exist_ok=True)
    export_config = dataclasses.replace(
        config.export_config, export_layers=("raw", "clean", "harmonize")
    )
    wide_config = dataclasses.replace(config, export_config=export_config)
    paths = export_processed_data(wide_config, _export_objects())
    assert set(paths) == {"test_raw", "test_clean", "test_harmonize"}
    assert all(path.is_file() for path in paths.values())


def test_export_no_matching_layer_raises(config: Config) -> None:
    config.paths.data.export.processed.mkdir(parents=True, exist_ok=True)
    objects = {"test_raw": _frame(), "test_clean": _frame()}
    with pytest.raises(ValidationError, match="harmonize"):
        export_processed_data(config, objects)
