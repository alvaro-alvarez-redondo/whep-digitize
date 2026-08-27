"""Tests for ingest reading: read_utils, sheet_read, batching.

Functional coverage: the read-result plumbing, sheet reading over the
real corpus and synthetic workbooks (missing base columns, header collisions, multi-sheet,
non-ASCII sheet names), batch splitting, worker resolution, and batch reading. Exact
Reference parity for the happy-path sheet read lives in ``tests/parity/test_sheet_read_parity.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pytest
import xlsxwriter
from polars.testing import assert_frame_equal

from whep_digitize.ingest.reading.batching import (
    BatchReadResult,
    read_workbook_batch,
    resolve_import_effective_workers,
    resolve_import_workbook_batch_size,
    split_workbook_batches,
)
from whep_digitize.ingest.reading.read_utils import (
    ReadResult,
    SafeReadResult,
    build_read_error,
    create_empty_read_result,
    has_read_errors,
    normalize_pipeline_read_result,
    safe_execute_read,
)
from whep_digitize.ingest.reading.sheet_read import (
    compute_non_empty_base_rows,
    read_excel_sheet,
    read_file_sheets,
    restore_numeric_text_precision,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.numeric import format_double_fixed
from whep_digitize.setup.options import RuntimeOptions

_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
_DATE_WB = _CORPUS / "fao_1949" / "fao_1949_crops" / "fao_1949_crops_92_92_date.xlsx"


def _write_xlsx(path: Path, sheets: dict[str, pl.DataFrame]) -> Path:
    """Write a multi-sheet workbook (column names become the header row)."""
    with xlsxwriter.Workbook(str(path)) as workbook:
        for name, frame in sheets.items():
            frame.write_excel(workbook=workbook, worksheet=name)
    return path


# --------------------------------------------------------------------------- read_utils


def test_build_read_error_uses_basename() -> None:
    msg = build_read_error("failed to read", "some/dir/data.xlsx", "boom")
    assert msg == "failed to read 'data.xlsx': boom"


def test_safe_execute_read_success() -> None:
    result = safe_execute_read(lambda: 42, "ctx", "f.xlsx")
    assert result == SafeReadResult(result=42, errors=())


def test_safe_execute_read_captures_exception() -> None:
    def boom() -> int:
        raise RuntimeError("kaboom")

    result = safe_execute_read(boom, "failed to read", "f.xlsx")
    assert result.result is None
    assert len(result.errors) == 1
    assert "kaboom" in result.errors[0]
    assert has_read_errors(result)


def test_create_empty_read_result() -> None:
    result = create_empty_read_result(["oops"])
    assert result.data.height == 0
    assert result.data.width == 0
    assert result.errors == ("oops",)


def test_normalize_pipeline_read_result_none() -> None:
    safe: SafeReadResult[ReadResult] = SafeReadResult(result=None, errors=("outer",))
    normalized = normalize_pipeline_read_result(safe)
    assert normalized.data.width == 0
    assert normalized.errors == ("outer",)


def test_normalize_pipeline_read_result_merges_errors() -> None:
    inner = ReadResult(data=pl.DataFrame({"a": ["x"]}), errors=("inner",))
    safe = SafeReadResult(result=inner, errors=("outer",))
    normalized = normalize_pipeline_read_result(safe)
    assert normalized.data.to_dict(as_series=False) == {"a": ["x"]}
    assert normalized.errors == ("outer", "inner")  # outer errors first


# --------------------------------------------------------------------------- sheet_read


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["x", None, "", "  ", "y"], [True, False, False, False, True]),
    ],
)
def test_compute_non_empty_base_rows(values: list[str | None], expected: list[bool]) -> None:
    frame = pl.DataFrame({"continent": values}, schema={"continent": pl.String})
    mask = compute_non_empty_base_rows(frame, ["continent"])
    assert mask.to_list() == expected


def test_compute_non_empty_base_rows_no_base_cols() -> None:
    frame = pl.DataFrame({"a": ["x", "y"]})
    assert compute_non_empty_base_rows(frame, []).to_list() == [False, False]


def test_read_excel_sheet_corpus_smoke(config: Config) -> None:
    result = read_excel_sheet(_DATE_WB, "production", config)
    assert result.errors == ()
    assert "polity" in result.data.columns  # country -> polity
    assert "country" not in result.data.columns
    assert result.data.columns[-1] == "variable"
    assert result.data["variable"].unique().to_list() == ["production"]
    assert result.data.height == 18


def test_read_excel_sheet_missing_base_column(config: Config, tmp_path: Path) -> None:
    wb = _write_xlsx(
        tmp_path / "missing.xlsx",
        {
            "production": pl.DataFrame(
                {
                    "continent": ["europe", "asia"],
                    "country": ["spain", "japan"],
                    "unit": ["t", "t"],
                    "1950": ["1", "2"],
                }
            )
        },
    )
    result = read_excel_sheet(wb, "production", config)
    assert len(result.errors) == 1
    assert "missing required base columns" in result.errors[0]
    assert "footnotes" in result.errors[0]
    assert "polity" in result.data.columns  # country renamed
    assert result.data["footnotes"].null_count() == result.data.height  # added all-null
    assert result.data["variable"].unique().to_list() == ["production"]


def test_read_excel_sheet_header_collision(config: Config, tmp_path: Path) -> None:
    # 'a b' and 'a_b' are distinct raw headers (no table dedup) that both normalize to
    # 'a_b' -> collision -> empty result + error (short-circuits before the missing-base check).
    wb = _write_xlsx(
        tmp_path / "collide.xlsx",
        {"production": pl.DataFrame({"continent": ["x"], "a b": ["y"], "a_b": ["z"]})},
    )
    result = read_excel_sheet(wb, "production", config)
    assert result.data.height == 0
    assert len(result.errors) == 1
    assert "collision" in result.errors[0]


def test_read_excel_sheet_missing_file(config: Config, tmp_path: Path) -> None:
    result = read_excel_sheet(tmp_path / "nope.xlsx", "production", config)
    assert result.data.width == 0
    assert has_read_errors(result)
    assert "failed to read sheet" in result.errors[0]


# ------------------------------------------------- float-precision repair (DB3 regression)


def test_restore_numeric_text_precision_rewrites_only_lossy_cells() -> None:
    # calamine renders ~12 significant digits: the first cell round-trips, the second does not.
    text = pl.DataFrame({"v": ["0.5", "0.1", "7.1"], "note": ["a", "b", "c"]})
    typed = pl.DataFrame({"v": [0.5, 0.09999999999999964, 7.1], "note": ["a", "b", "c"]})
    repaired = restore_numeric_text_precision(text, typed)
    assert repaired.get_column("v").to_list() == ["0.5", "0.09999999999999964", "7.1"]
    assert repaired.get_column("note").to_list() == ["a", "b", "c"]


def test_restore_numeric_text_precision_is_noop_when_faithful() -> None:
    text = pl.DataFrame({"v": ["0.5", "30", None]})
    typed = pl.DataFrame({"v": [0.5, 30.0, None]})
    repaired = restore_numeric_text_precision(text, typed)
    assert repaired.get_column("v").to_list() == ["0.5", "30", None]


def test_restore_numeric_text_precision_drops_trailing_dot_zero() -> None:
    # A lossy *integral* value must be rewritten in shortest round-trip form: no ".0".
    text = pl.DataFrame({"v": ["1.23456789012e+14"]})
    typed = pl.DataFrame({"v": [123456789012345.0]})
    repaired = restore_numeric_text_precision(text, typed)
    assert repaired.get_column("v").to_list() == ["123456789012345"]


def test_restore_numeric_text_precision_ignores_misaligned_reads() -> None:
    text = pl.DataFrame({"v": ["0.1"]})
    typed = pl.DataFrame({"v": [0.09999999999999964, 1.0]})
    assert restore_numeric_text_precision(text, typed).get_column("v").to_list() == ["0.1"]


def test_read_excel_sheet_preserves_stored_double(config: Config, tmp_path: Path) -> None:
    # DB3: the workbook stores 0.09999999999999964; calamine's text coercion rounds it to "0.1",
    # which a x1000 unit standardization then turns into 100.
    wb = _write_xlsx(
        tmp_path / "imprecise.xlsx",
        {
            "exports": pl.DataFrame(
                {
                    "continent": ["asia"],
                    "country": ["indes neerlandaises"],
                    "unit": ["1000 quintals"],
                    "footnotes": ["lint"],
                    "1933": [0.09999999999999964],
                }
            )
        },
    )
    result = read_excel_sheet(wb, "exports", config)
    cell = result.data.get_column("1933").item(0)
    assert cell == "0.09999999999999964"  # the exact stored value
    assert format_double_fixed(float(cell) * 1000) == "99.9999999999996"


def test_read_file_sheets_multi_sheet(config: Config, tmp_path: Path) -> None:
    base = pl.DataFrame(
        {"continent": ["europe"], "polity": ["spain"], "unit": ["t"], "footnotes": [None]},
        schema={
            "continent": pl.String,
            "polity": pl.String,
            "unit": pl.String,
            "footnotes": pl.String,
        },
    )
    wb = _write_xlsx(tmp_path / "multi.xlsx", {"production": base, "trade": base})
    result = read_file_sheets(wb, config)
    assert result.data.height == 2
    assert sorted(result.data["variable"].to_list()) == ["production", "trade"]


def test_read_file_sheets_explicit_sheet_names(config: Config, tmp_path: Path) -> None:
    base = pl.DataFrame(
        {"continent": ["europe"], "polity": ["spain"], "unit": ["t"], "footnotes": [None]},
        schema={
            "continent": pl.String,
            "polity": pl.String,
            "unit": pl.String,
            "footnotes": pl.String,
        },
    )
    wb = _write_xlsx(tmp_path / "multi2.xlsx", {"production": base, "trade": base})
    result = read_file_sheets(wb, config, sheet_names=["production"])
    assert result.data["variable"].unique().to_list() == ["production"]


def test_read_file_sheets_non_ascii_sheet_name_warns(config: Config, tmp_path: Path) -> None:
    base = pl.DataFrame(
        {"continent": ["europe"], "polity": ["spain"], "unit": ["t"], "footnotes": [None]},
        schema={
            "continent": pl.String,
            "polity": pl.String,
            "unit": pl.String,
            "footnotes": pl.String,
        },
    )
    wb = _write_xlsx(tmp_path / "accent.xlsx", {"café": base})
    result = read_file_sheets(wb, config)
    assert any("non-ascii sheet names" in err for err in result.errors)


# --------------------------------------------------------------------------- batching


@pytest.mark.parametrize(
    ("paths", "size", "expected"),
    [
        (["a", "b", "c"], 2, [["a", "b"], ["c"]]),
        (["a", "b", "c", "d"], 2, [["a", "b"], ["c", "d"]]),
        (["a", "b"], 5, [["a", "b"]]),
        ([], 2, []),
        (None, 2, []),
    ],
)
def test_split_workbook_batches(
    paths: list[str] | None, size: int, expected: list[list[str]]
) -> None:
    assert split_workbook_batches(paths, size) == expected


def test_split_workbook_batches_bad_size() -> None:
    with pytest.raises(ValidationError):
        split_workbook_batches(["a"], 0)


def test_resolve_import_workbook_batch_size(config: Config) -> None:
    assert resolve_import_workbook_batch_size(config) == 32


def test_resolve_effective_workers_auto(config: Config) -> None:
    workers = resolve_import_effective_workers(
        config, RuntimeOptions(ingest_parallel_workers="auto")
    )
    expected = max(1, min(8, (os.cpu_count() or 1) - 1))
    assert workers == expected


@pytest.mark.parametrize(("setting", "expected"), [(4, 4), (1, 1), (0, 1), (-3, 1)])
def test_resolve_effective_workers_explicit(config: Config, setting: int, expected: int) -> None:
    workers = resolve_import_effective_workers(
        config, RuntimeOptions(ingest_parallel_workers=setting)
    )
    assert workers == expected


def test_read_workbook_batch_empty(config: Config) -> None:
    assert read_workbook_batch([], config) == BatchReadResult(read_data_list=(), errors=())


def test_read_workbook_batch_dedup_shares_frame(config: Config) -> None:
    result = read_workbook_batch([str(_DATE_WB), str(_DATE_WB)], config)
    assert len(result.read_data_list) == 2  # one frame per input path, duplicates repeated
    assert_frame_equal(result.read_data_list[0], result.read_data_list[1])
    assert result.errors == ()


def test_read_workbook_batch_collects_errors(config: Config, tmp_path: Path) -> None:
    result = read_workbook_batch([str(_DATE_WB), str(tmp_path / "nope.xlsx")], config)
    assert len(result.read_data_list) == 2
    assert result.read_data_list[1].width == 0  # failed read -> empty frame
    assert any("failed to list sheets" in err for err in result.errors)
