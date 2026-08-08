"""Tests for ingest header normalization (``ingest.reading.header_normalization``).

Functional coverage: the ordered normalization chain, the fast-path
short-circuit, the canonical + ``country``->``polity`` alias renames with every collision
guard, and collision validation. Reference parity (incl. the accented/unicode
transliteration) lives in ``tests/parity/test_header_normalization_parity.py``.
"""

from __future__ import annotations

import pytest

from whep_digitize.ingest.reading.header_normalization import (
    HeaderRenames,
    normalize_header_name,
    normalize_header_names,
    resolve_canonical_header_renames,
    validate_header_normalization,
)
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.strings import normalize_text, transliterate_ascii_lower

_CANON = ["continent", "polity", "unit", "footnotes", "commodity", "variable", "hemisphere"]


# --------------------------------------------------------------------------- chain


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Country  ", "country"),  # trim
        ("North   America", "north_america"),  # whitespace collapse -> _
        ("Year / Period", "year/period"),  # separator padding stripped, / kept
        ("value - amount", "value-amount"),  # - kept
        ("GDP  (current US$)", "gdp_current_us"),  # punctuation -> _, trailing _ trimmed
        ("café résumé", "cafe_resume"),  # transliteration
        ("a__b", "a_b"),  # multi-underscore collapse
        ("_leading_", "leading"),  # trim underscores
        ("__x__", "x"),
        ("value %", "value"),  # % -> _ -> trimmed
        ("%", ""),  # all-punctuation collapses to empty
        ("", ""),  # empty stays empty
        ("½ unit", "unit"),  # policy: ½ has no ASCII base -> dropped (no expansion)
    ],
)
def test_normalize_header_name(raw: str, expected: str) -> None:
    assert normalize_header_name(raw) == expected


def test_normalize_header_names_preserves_none() -> None:
    assert normalize_header_names(["Continent", None, "Country Name"]) == [
        "continent",
        None,
        "country_name",
    ]


def test_normalize_header_names_all_none() -> None:
    assert normalize_header_names([None, None]) == [None, None]


def test_normalize_header_names_empty() -> None:
    assert normalize_header_names([]) == []


def test_fast_path_returns_already_clean_unchanged() -> None:
    clean = ["continent", "a-b", "x/y", "hemisphere", "a_b"]
    assert normalize_header_names(clean) == clean


def test_fast_path_falls_through_on_double_underscore() -> None:
    # Matches the fast-path pattern but carries a collapsible "__": must still normalize.
    assert normalize_header_names(["a__b", "c"]) == ["a_b", "c"]


def test_shared_transliteration_with_match_keys() -> None:
    # Header + match-key normalization must fold identically (one transliteration source).
    assert transliterate_ascii_lower("Résumé") == "resume"
    assert normalize_header_name("Résumé") == "resume"
    assert normalize_text("Résumé") == "resume"
    # Policy consequence: ß has no canonical decomposition, so it is dropped (not folded to
    # "ss" as a compatibility fold would) — identically by both entry points.
    assert normalize_header_name("groß") == "gro"
    assert normalize_text("groß") == "gro"


# --------------------------------------------------------------------------- renames


def test_resolve_canonical_basic() -> None:
    raw = ["Continent", "Unit"]
    result = resolve_canonical_header_renames(raw, normalize_header_names(raw), _CANON)
    assert result == HeaderRenames(old=("Continent", "Unit"), new=("continent", "unit"))


def test_resolve_has_exact_name_skips_rename() -> None:
    # 'continent' already present verbatim -> no rename (and it cannot be stolen).
    raw = ["continent", "Region"]
    result = resolve_canonical_header_renames(raw, normalize_header_names(raw), _CANON)
    assert result == HeaderRenames(old=(), new=())


def test_resolve_alias_country_to_polity() -> None:
    raw = ["Country", "Continent"]
    result = resolve_canonical_header_renames(raw, normalize_header_names(raw), _CANON)
    assert result == HeaderRenames(old=("Continent", "Country"), new=("continent", "polity"))


def test_resolve_alias_guarded_when_target_present() -> None:
    # 'polity' already a header -> the country alias must not fire.
    raw = ["Country", "polity"]
    result = resolve_canonical_header_renames(raw, normalize_header_names(raw), _CANON)
    assert result == HeaderRenames(old=(), new=())


def test_resolve_alias_duplicate_target_dedup() -> None:
    # Two aliases -> polity: only the first survives (duplicated-target guard).
    raw = ["Country", "Nation", "Continent"]
    result = resolve_canonical_header_renames(
        raw,
        normalize_header_names(raw),
        _CANON,
        alias_map={"country": "polity", "nation": "polity"},
    )
    assert result == HeaderRenames(old=("Continent", "Country"), new=("continent", "polity"))


def test_resolve_empty_canonical() -> None:
    result = resolve_canonical_header_renames(["A"], normalize_header_names(["A"]), [])
    assert result == HeaderRenames(old=(), new=())


def test_resolve_length_mismatch_raises() -> None:
    with pytest.raises(ValidationError):
        resolve_canonical_header_renames(["A", "B"], ["a"], _CANON)


# --------------------------------------------------------------------------- validate


def test_validate_detects_collision() -> None:
    raw = ["A B", "A  B", "C"]
    errors = validate_header_normalization(raw, normalize_header_names(raw), "f.xlsx", "Sheet1")
    assert len(errors) == 1
    assert "a_b" in errors[0]


def test_validate_no_collision() -> None:
    raw = ["X", "Y"]
    assert validate_header_normalization(raw, normalize_header_names(raw), "f.xlsx", "S") == []


def test_validate_ignores_empty_normalized() -> None:
    # '%' and '@' normalize to "" and must not be treated as a collision.
    raw = ["%", "@"]
    assert validate_header_normalization(raw, normalize_header_names(raw), "f.xlsx", "S") == []


def test_validate_message_content() -> None:
    raw = ["A B", "A  B"]
    errors = validate_header_normalization(
        raw, normalize_header_names(raw), "some/dir/report.xlsx", "Sheet1"
    )
    assert errors[0] == (
        "normalized header collision detected in sheet 'Sheet1' for file 'report.xlsx': a_b"
    )


def test_validate_length_mismatch_raises() -> None:
    with pytest.raises(ValidationError):
        validate_header_normalization(["A", "B"], ["a"], "f.xlsx", "S")


@pytest.mark.parametrize(("file_path", "sheet_name"), [("", "S"), ("f.xlsx", "")])
def test_validate_blank_args_raise(file_path: str, sheet_name: str) -> None:
    with pytest.raises(ValidationError):
        validate_header_normalization(["A"], ["a"], file_path, sheet_name)
