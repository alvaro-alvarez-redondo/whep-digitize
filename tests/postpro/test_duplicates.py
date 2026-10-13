"""Unit tests for the post-processing duplicate audit.

Covers :mod:`whep_digitize.postpro.diagnostics.duplicates` — the two duplication criteria,
the exported subset, and the header-only contract for clean or empty layers.
"""

from __future__ import annotations

import polars as pl
import pytest

from whep_digitize.postpro.diagnostics.duplicates import (
    DUP_EXCL_VALUE_COLUMN,
    DUP_FULL_COLUMN,
    build_duplicate_audit,
    persist_duplicate_audits,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError


def _frame(**columns: list[str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in columns.items()}
    )


def test_flags_both_criteria_independently() -> None:
    """A row duplicated only once ``value`` is ignored is kept, flagged ``dup_full`` false.

    ``wheat/1950`` appears three times with two distinct values: the two identical rows are
    duplicated under both criteria, the odd one only under ``dup_excl_value``. That row — the
    same record carrying a conflicting value — is the point of the audit.
    """
    frame = _frame(
        commodity=["wheat", "wheat", "wheat", "rice"],
        year=["1950", "1950", "1950", "1951"],
        value=["10", "10", "99", "5"],
    )

    audit = build_duplicate_audit(frame)

    assert audit.height == 3, "the unique 'rice' row must not be exported"
    assert audit.get_column("value").to_list() == ["10", "10", "99"]
    assert audit.get_column(DUP_FULL_COLUMN).to_list() == [True, True, False]
    assert audit.get_column(DUP_EXCL_VALUE_COLUMN).to_list() == [True, True, True]


def test_exports_only_rows_duplicated_excluding_value() -> None:
    """Rows unique on the non-``value`` columns are excluded even when values repeat."""
    frame = _frame(
        commodity=["wheat", "rice"],
        year=["1950", "1951"],
        value=["7", "7"],
    )

    assert build_duplicate_audit(frame).height == 0


def test_flag_columns_are_appended_after_the_source_columns() -> None:
    """The exported schema is the source schema plus exactly the two boolean flags."""
    frame = _frame(commodity=["a", "a"], year=["1", "1"], value=["2", "2"])

    audit = build_duplicate_audit(frame)

    assert audit.columns == ["commodity", "year", "value", DUP_FULL_COLUMN, DUP_EXCL_VALUE_COLUMN]
    assert audit.schema[DUP_FULL_COLUMN] == pl.Boolean
    assert audit.schema[DUP_EXCL_VALUE_COLUMN] == pl.Boolean


def test_frame_without_duplicates_keeps_header_only() -> None:
    """A clean layer still yields a full header, so "audited, nothing found" is readable."""
    frame = _frame(commodity=["a", "b"], value=["1", "2"])

    audit = build_duplicate_audit(frame)

    assert audit.height == 0
    assert audit.columns == ["commodity", "value", DUP_FULL_COLUMN, DUP_EXCL_VALUE_COLUMN]


def test_empty_frame_keeps_header_and_dtypes() -> None:
    """An empty input preserves its own dtypes, not a collapsed all-string schema."""
    frame = pl.DataFrame(schema={"commodity": pl.String, "value": pl.Float64})

    audit = build_duplicate_audit(frame)

    assert audit.height == 0
    assert audit.schema["value"] == pl.Float64
    assert audit.schema[DUP_FULL_COLUMN] == pl.Boolean


def test_missing_value_column_makes_both_criteria_identical() -> None:
    """With no ``value`` column to exclude, the two criteria describe the same thing."""
    frame = _frame(commodity=["x", "x", "y"], year=["1", "1", "2"])

    audit = build_duplicate_audit(frame)

    assert audit.height == 2
    assert audit.get_column(DUP_FULL_COLUMN).to_list() == [True, True]
    assert audit.get_column(DUP_EXCL_VALUE_COLUMN).to_list() == [True, True]


def test_value_only_frame_has_no_identity_to_duplicate() -> None:
    """A frame that is nothing but ``value`` has no key columns, so nothing is reported."""
    frame = _frame(value=["1", "1"])

    audit = build_duplicate_audit(frame)

    assert audit.height == 0
    assert audit.columns == ["value", DUP_FULL_COLUMN, DUP_EXCL_VALUE_COLUMN]


def test_nulls_compare_equal() -> None:
    """Rows jointly missing a field still count as duplicates (polars grouping semantics)."""
    frame = _frame(commodity=[None, None], value=["1", "2"])

    assert build_duplicate_audit(frame).height == 2


def test_row_order_follows_the_input() -> None:
    """Order is inherited from the input, so a deterministic layer yields a deterministic audit."""
    frame = _frame(
        commodity=["b", "a", "b", "a"],
        year=["2", "1", "2", "1"],
        value=["9", "8", "9", "8"],
    )

    assert build_duplicate_audit(frame).get_column("commodity").to_list() == ["b", "a", "b", "a"]


def test_reserved_flag_column_is_rejected() -> None:
    """Overwriting a caller's own ``dup_full`` column silently would corrupt their data."""
    frame = pl.DataFrame({"commodity": ["a"], DUP_FULL_COLUMN: [True], "value": ["1"]})

    with pytest.raises(ValidationError):
        build_duplicate_audit(frame)


def test_persist_writes_one_tsv_per_layer(config: Config) -> None:
    """Every layer gets a file, including the ones with nothing to report."""
    with_dups = _frame(commodity=["a", "a"], value=["1", "2"])
    without_dups = _frame(commodity=["a", "b"], value=["1", "2"])

    paths = persist_duplicate_audits(
        {"raw": with_dups, "clean": without_dups, "normalize": without_dups,
         "harmonize": with_dups},
        config,
    )

    assert set(paths) == {"raw", "clean", "normalize", "harmonize"}
    for layer, path in paths.items():
        assert path.is_file(), f"{layer} must be written even when it has no duplicates"
        assert path.name == f"{layer}_dup.tsv"
        assert path.parent == config.paths.data.audit.duplicates_dir

    populated = pl.read_csv(paths["raw"], separator="\t")
    assert populated.height == 2
    assert DUP_FULL_COLUMN in populated.columns

    # A layer with no duplicates is written as a header row and nothing else.
    empty_text = paths["clean"].read_text(encoding="utf-8").splitlines()
    assert len(empty_text) == 1
    assert empty_text[0].split("\t") == ["commodity", "value", DUP_FULL_COLUMN,
                                         DUP_EXCL_VALUE_COLUMN]


def test_persist_creates_the_duplicates_directory(config: Config) -> None:
    """The directory is created on write, not eagerly by stage 0."""
    duplicates_dir = config.paths.data.audit.duplicates_dir
    assert not duplicates_dir.exists()

    persist_duplicate_audits({"clean": _frame(commodity=["a"], value=["1"])}, config)

    assert duplicates_dir.is_dir()
