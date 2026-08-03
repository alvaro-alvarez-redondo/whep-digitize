"""Tests for the shared helpers (strings, numeric, sorting, frames, time, tokens, checkpoints)."""

from __future__ import annotations

import polars as pl
import pytest
from polars.testing import assert_series_equal

from whep_digitize.setup.config import Config
from whep_digitize.setup.helpers import (
    checkpoints,
    frames,
    numeric,
    sorting,
    strings,
    time_format,
    tokens,
)

# --------------------------------------------------------------------------- strings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hello, World!", "hello world"),
        ("Café  Región", "cafe region"),
        ("ÑOÑO", "nono"),
        ("  spaced  out  ", "spaced out"),
        ("", ""),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert strings.normalize_text(raw) == expected


def test_normalize_text_none() -> None:
    assert strings.normalize_text(None) is None


def test_normalize_string_series_preserves_nulls() -> None:
    series = pl.Series("polity", ["Éire", None, "España"])
    result = strings.normalize_string(series)
    assert result.to_list() == ["eire", None, "espana"]


def test_clean_footnote_preserves_punctuation() -> None:
    assert strings.clean_footnote("See note (a); ref #3.") == "see note (a); ref #3."


def test_normalize_filename() -> None:
    assert strings.normalize_filename("FAO 1961 Wheat") == "fao_1961_wheat"
    assert strings.normalize_filename("") == "unknown"
    assert strings.normalize_filename(None) == "unknown"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("café", "cafe"),  # accented Latin letters fold to their ASCII base
        ("ÑOÑO", "nono"),
        ("Kuršėnai", "kursenai"),
        ("Straße", "straße"),  # ß has no canonical decomposition -> left for the non-alnum step
        ("½", "½"),  # symbols are NOT expanded passed through untouched
        ("±", "±"),
        ("®", "®"),
        ("¹", "¹"),  # superscripts are NOT folded to digits (compatibility rule avoided)
    ],
)
def test_transliterate_ascii_lower_policy(raw: str, expected: str) -> None:
    # Policy: strip diacritics via NFD + lowercase; do NOT apply symbol / compatibility
    # expansions. Non-decomposable codepoints pass through for the caller's non-alnum step to drop.
    assert strings.transliterate_ascii_lower(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Philippines®", "philippines"),  # ® dropped, NOT expanded to "philippines r"
        ("½ kg", "kg"),  # ½ dropped, NOT "1 2 kg"
        ("Straße", "stra e"),  # ß dropped (no canonical decomposition)
        ("Belgian Congo¹", "belgian congo"),  # superscript marker becomes a separator
        ("naïve café", "naive cafe"),  # diacritics folded to ASCII base
        ("γ-ray", "ray"),  # noqa: RUF001  (non-Latin script has no ASCII base, dropped)
    ],
)
def test_normalize_text_policy(raw: str, expected: str) -> None:
    # End-to-end policy: fold diacritics, drop every non-[a-z0-9] char (symbols, non-Latin
    # scripts, non-decomposable letters), collapse runs to a single space, trim.
    assert strings.normalize_text(raw) == expected


# --------------------------------------------------------------------------- numeric


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.5", 2.5),
        (" 3 ", 3.0),
        (10, 10.0),
        ("", None),
        ("abc", None),
        (None, None),
        (True, None),
    ],
)
def test_coerce_numeric(raw: object, expected: float | None) -> None:
    assert numeric.coerce_numeric(raw) == expected  # type: ignore[arg-type]


def test_coerce_numeric_series() -> None:
    series = pl.Series("value", ["1.0", " 2 ", "bad", "", None])
    result = numeric.coerce_numeric_series(series)
    assert result.to_list() == [1.0, 2.0, None, None, None]


# --------------------------------------------------------------------------- sorting


def test_sort_pipeline_stage_df(sample_long_df: pl.DataFrame) -> None:
    result = sorting.sort_pipeline_stage_df(sample_long_df)
    # Canonical order sorts by hemisphere, continent, polity, ... with nulls last.
    assert result["polity"].to_list() == ["japan", "spain", "france"]


def test_sort_ignores_absent_columns() -> None:
    frame = pl.DataFrame({"polity": ["b", "a"], "extra": [1, 2]})
    result = sorting.sort_pipeline_stage_df(frame)
    assert result["polity"].to_list() == ["a", "b"]


# --------------------------------------------------------------------------- frames


def test_drop_na_value_rows(sample_long_df: pl.DataFrame) -> None:
    result = frames.drop_na_value_rows(sample_long_df)
    assert result.height == 2
    assert result["value"].null_count() == 0


def test_drop_na_value_rows_disabled(sample_long_df: pl.DataFrame) -> None:
    result = frames.drop_na_value_rows(sample_long_df, enabled=False)
    assert result.height == sample_long_df.height


# --------------------------------------------------------------------------- time


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(5, "5s"), (65, "1m 5s"), (3725, "1h 2m")],
)
def test_format_elapsed_time(seconds: float, expected: str) -> None:
    assert time_format.format_elapsed_time(seconds) == expected


# --------------------------------------------------------------------------- tokens


def test_extract_yearbook() -> None:
    parts = ["fao", "trade", "x", "1961"]
    assert tokens.extract_yearbook(parts) == "trade_1961"


def test_extract_yearbook_requires_year() -> None:
    assert tokens.extract_yearbook(["fao", "trade"]) is None
    assert tokens.extract_yearbook(["fao"]) is None


def test_extract_commodity() -> None:
    parts = ["a", "b", "c", "d", "e", "f", "wheat", "flour.xlsx"]
    assert tokens.extract_commodity(parts) == "wheat_flour"


def test_extract_commodity_too_few_parts() -> None:
    assert tokens.extract_commodity(["a", "b", "c"]) is None


# --------------------------------------------------------------------------- checkpoints


def test_checkpoint_round_trip(config: Config) -> None:
    frame = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    path = checkpoints.save_checkpoint("import_pipeline", frame, config, enabled=True)
    assert path is not None
    loaded = checkpoints.load_checkpoint("import_pipeline", config, enabled=True)
    assert isinstance(loaded, pl.DataFrame)
    assert_series_equal(loaded["a"], frame["a"])


def test_checkpoint_disabled_is_noop(config: Config) -> None:
    frame = pl.DataFrame({"a": [1]})
    assert checkpoints.save_checkpoint("x", frame, config, enabled=False) is None
    assert checkpoints.load_checkpoint("x", config, enabled=False) is None
