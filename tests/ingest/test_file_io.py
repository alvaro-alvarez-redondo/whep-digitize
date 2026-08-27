"""Tests for ingest file IO — discovery + file-name metadata (``ingest.file_io``).

Functional coverage: discovery against the real committed corpus
(sorted forward-slash paths, filtering, recursion, empty/blank/missing folders) and metadata
token parsing across every branch. Reference parity lives in
``tests/parity/test_file_metadata_parity.py``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from whep_digitize.ingest.file_io.discovery import discover_files, discover_pipeline_files
from whep_digitize.ingest.file_io.metadata import build_empty_file_metadata, extract_file_metadata
from whep_digitize.setup.config import load_pipeline_config
from whep_digitize.setup.errors import ValidationError

_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"

_METADATA_COLUMNS = ["file_path", "file_name", "commodity", "yearbook", "is_ascii", "error_message"]

# Ground truth for the committed corpus, verified against the committed fixtures
# (sorted by full path string). See tests/parity for the byte-for-byte golden comparison.
_CORPUS_FILE_NAMES = [
    "fao_1949_crops_92_92_date.xlsx",
    "fao_1949_livestock_162_162_milk.xlsx",
    "fao_1949_population_24_24_population_agriculture.xlsx",
    "fao_1950_trade_106_106_palm_kernel_oil.xlsx",
    "fao_1952_land_3_9_irrigation_permanent_meadows_pastures.xlsx",
    "fao_1955_inputs_228_229_pesticide_fluoride.xlsx",
]
_CORPUS_YEARBOOKS = ["fao_1949", "fao_1949", "fao_1949", "fao_1950", "fao_1952", "fao_1955"]
_CORPUS_COMMODITIES = [
    "date",
    "milk",
    "population_agriculture",
    "palm_kernel_oil",
    "irrigation_permanent_meadows_pastures",
    "pesticide_fluoride",
]


# --------------------------------------------------------------------------- discovery


def test_discover_files_corpus_metadata() -> None:
    result = discover_files(_CORPUS)
    assert result.columns == _METADATA_COLUMNS
    assert result.height == len(_CORPUS_FILE_NAMES)
    assert result["file_name"].to_list() == _CORPUS_FILE_NAMES
    assert result["yearbook"].to_list() == _CORPUS_YEARBOOKS
    assert result["commodity"].to_list() == _CORPUS_COMMODITIES
    assert result["is_ascii"].to_list() == [True] * len(_CORPUS_FILE_NAMES)
    assert result["error_message"].to_list() == [None] * len(_CORPUS_FILE_NAMES)


def test_discover_files_paths_sorted_and_posix() -> None:
    result = discover_files(_CORPUS)
    file_paths = result["file_path"].to_list()
    prefix = _CORPUS.as_posix()
    assert file_paths == sorted(file_paths)  # fs::dir_ls C-locale / codepoint order
    assert all("\\" not in path for path in file_paths)  # forward slashes only, like fs
    for path, name in zip(file_paths, _CORPUS_FILE_NAMES, strict=True):
        assert path.startswith(f"{prefix}/")
        assert path.endswith(f"/{name}")


def test_discover_files_relative_path_stays_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "fao_1961_x_y_z_z_wheat.xlsx").touch()
    # A relative import folder must yield relative forward-slash paths (fs behaviour).
    monkeypatch.chdir(tmp_path)
    result = discover_files("sub")
    assert result["file_path"].to_list() == ["sub/fao_1961_x_y_z_z_wheat.xlsx"]


def test_discover_files_recurses_and_filters(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "top_2000_a_b_c_c_wheat.xlsx").touch()
    (tmp_path / "nested" / "deep_2001_a_b_c_c_rice.xlsx").touch()
    (tmp_path / "notes.txt").touch()
    (tmp_path / "data.csv").touch()
    result = discover_files(tmp_path)
    assert result["file_name"].to_list() == [
        "deep_2001_a_b_c_c_rice.xlsx",
        "top_2000_a_b_c_c_wheat.xlsx",
    ]


def test_discover_files_extension_match_is_case_sensitive(tmp_path: Path) -> None:
    # Discovery matches `*.xlsx` case-sensitively; an uppercase extension
    # must not be discovered even on a case-insensitive filesystem.
    (tmp_path / "report_2000_a_b_c_c_wheat.XLSX").touch()
    with pytest.warns(UserWarning, match="no xlsx files"):
        result = discover_files(tmp_path)
    assert result.height == 0


def test_discover_files_empty_folder_warns_and_returns_empty(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="no xlsx files were found"):
        result = discover_files(tmp_path)
    assert result.height == 0
    assert result.columns == _METADATA_COLUMNS


def test_discover_files_missing_directory_raises() -> None:
    with pytest.raises(ValidationError):
        discover_files(_CORPUS / "does_not_exist")


def test_discover_files_blank_path_raises() -> None:
    with pytest.raises(ValidationError):
        discover_files("")


def test_discover_pipeline_files(tmp_path: Path) -> None:
    config = load_pipeline_config(root=tmp_path)
    raw = config.paths.data.input.raw
    raw.mkdir(parents=True)
    (raw / "fao_1949_crops_92_92_date.xlsx").touch()
    (raw / "fao_1950_trade_106_106_palm_kernel_oil.xlsx").touch()
    result = discover_pipeline_files(config)
    assert result["file_name"].to_list() == [
        "fao_1949_crops_92_92_date.xlsx",
        "fao_1950_trade_106_106_palm_kernel_oil.xlsx",
    ]
    assert result["yearbook"].to_list() == ["fao_1949", "fao_1950"]
    assert result["commodity"].to_list() == ["date", "palm_kernel_oil"]


# --------------------------------------------------------------------------- metadata


def test_extract_file_metadata_schema_and_dtypes() -> None:
    result = extract_file_metadata(["fao_1949_crops_92_92_date.xlsx"])
    assert result.columns == _METADATA_COLUMNS
    assert result.schema["file_path"] == pl.String
    assert result.schema["commodity"] == pl.String
    assert result.schema["yearbook"] == pl.String
    assert result.schema["is_ascii"] == pl.Boolean
    assert result.schema["error_message"] == pl.String


def test_extract_file_metadata_basename_and_verbatim_path() -> None:
    path = "some/nested/dir/fao_1949_crops_92_92_date.xlsx"
    result = extract_file_metadata([path])
    assert result["file_path"].to_list() == [path]  # retained verbatim
    assert result["file_name"].to_list() == ["fao_1949_crops_92_92_date.xlsx"]
    assert result["yearbook"].to_list() == ["fao_1949"]
    assert result["commodity"].to_list() == ["date"]


def test_extract_file_metadata_first_year_token_wins() -> None:
    result = extract_file_metadata(["fao_1961_a_b_c_2000_wheat.xlsx"])
    assert result["yearbook"].to_list() == ["fao_1961"]
    assert result["commodity"].to_list() == ["2000_wheat"]


@pytest.mark.parametrize(
    ("name", "yearbook", "commodity"),
    [
        ("fao_1961_crops_1_1.xlsx", "fao_1961", None),  # <=5 tokens -> no commodity
        ("fao_crops_wheat.xlsx", None, None),  # no 4-digit token -> no yearbook
        ("2020.xlsx", None, None),  # <2 tokens -> no yearbook
    ],
)
def test_extract_file_metadata_none_branches(
    name: str, yearbook: str | None, commodity: str | None
) -> None:
    result = extract_file_metadata([name])
    assert result["yearbook"].to_list() == [yearbook]
    assert result["commodity"].to_list() == [commodity]


def test_extract_file_metadata_non_ascii() -> None:
    name = "fao_1949_a_b_c_wheat_café.xlsx"
    result = extract_file_metadata([name])
    assert result["is_ascii"].to_list() == [False]
    assert result["error_message"].to_list() == [f"non-ascii file name detected: {name}"]
    assert result["commodity"].to_list() == ["wheat_café"]  # not transliterated here
    assert result["yearbook"].to_list() == ["fao_1949"]


def test_extract_file_metadata_all_null_token_columns_stay_string() -> None:
    # All inputs lack tokens: commodity/yearbook must remain String, never inferred Null.
    result = extract_file_metadata(["2020.xlsx", "2021.xlsx"])
    assert result.schema["commodity"] == pl.String
    assert result.schema["yearbook"] == pl.String
    assert result["commodity"].to_list() == [None, None]


def test_extract_file_metadata_empty_raises() -> None:
    with pytest.raises(ValidationError):
        extract_file_metadata([])


def test_build_empty_file_metadata() -> None:
    result = build_empty_file_metadata()
    assert result.height == 0
    assert result.columns == _METADATA_COLUMNS
    assert result.schema["is_ascii"] == pl.Boolean
    assert result.schema["file_path"] == pl.String
