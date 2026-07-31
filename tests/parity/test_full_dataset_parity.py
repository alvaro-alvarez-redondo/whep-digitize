"""Full-dataset R-vs-Python parity.

The end-to-end test is ``@pytest.mark.slow`` and therefore excluded from the default suite
(``addopts = -m "not slow"``): it needs the R oracle *and* the ~1,339-workbook production
dataset, neither of which exists in CI. Run it with::

    .venv/Scripts/python.exe -m pytest -m slow

Everything else here is pure logic that runs in the default suite — it is what keeps the
"accepted normalization divergence" rule honest, and it is the part that would silently rot if
only the opt-in test covered it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parity_full_dataset import (
    ComparisonReport,
    PreconditionError,
    check_parity,
    classify_difference,
    classify_set_rows,
    classify_unmatched_rows,
    describe_row_difference,
    is_subsequence,
    read_tsv,
    resolve_r_project,
    value_sum,
)

COLUMNS = ["polity", "commodity", "year", "value"]


# ---------------------------------------------------------------------------
# Divergence classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("needle", "haystack", "expected"),
    [
        ("", "abc", True),
        ("abc", "abc", True),
        ("ac", "abc", True),
        ("philippines", "philippines r", True),
        ("nicaragus", "nicaragus r", True),
        ("abcd", "abc", False),
        ("ca", "abc", False),
        ("nicaragua", "nicaragus", False),
    ],
)
def test_is_subsequence(needle: str, haystack: str, expected: bool) -> None:
    assert is_subsequence(needle, haystack) is expected


@pytest.mark.parametrize(
    ("r_value", "py_value"),
    [
        # ICU expands the characters the policy drops, so Python's value is always
        # reachable from R's by deleting characters (r-to-python-mapping.md risk #1).
        ("philippines r", "philippines"),  # ICU (R) for the registered-trademark sign
        ("uruguay r", "uruguay"),
        ("cafe 1 2", "cafe"),  # ICU 1/2 for the vulgar fraction
        ("strasse", "strae"),  # ICU ss for eszett
        ("identical", "identical"),
    ],
)
def test_classify_difference_accepts_policy_divergence(r_value: str, py_value: str) -> None:
    accepted, reason = classify_difference(r_value, py_value)
    assert accepted, reason


@pytest.mark.parametrize(
    ("r_value", "py_value", "reason_fragment"),
    [
        ("philippines", "", "blanked"),  # a blanked field is never an accepted divergence
        ("1234.5", "1234.6", "not reachable"),  # a changed number
        ("nicaragus", "nicaragua", "not reachable"),  # a substitution, not a deletion
        ("wheat", "barley", "not reachable"),  # an outright different value
        ("philippines", "philippines r", "not reachable"),  # divergence in the wrong direction
    ],
)
def test_classify_difference_rejects_real_defects(
    r_value: str, py_value: str, reason_fragment: str
) -> None:
    accepted, reason = classify_difference(r_value, py_value)
    assert not accepted
    assert reason_fragment in reason


def test_describe_row_difference_rejects_invariant_column_change() -> None:
    r_row = ("philippines r", "cotton", "1933", "100")
    py_row = ("philippines", "cotton", "1933", "99.9")
    accepted, descriptions = describe_row_difference(r_row, py_row, COLUMNS)
    assert not accepted
    assert any("value must never differ" in d for d in descriptions)


def test_describe_row_difference_accepts_text_only_change() -> None:
    r_row = ("philippines r", "cotton", "1933", "100")
    py_row = ("philippines", "cotton", "1933", "100")
    accepted, descriptions = describe_row_difference(r_row, py_row, COLUMNS)
    assert accepted
    assert descriptions == ["polity: 'philippines r' -> 'philippines'"]


# ---------------------------------------------------------------------------
# Row matching — the part that makes the harness resistant to sort-order drift
# ---------------------------------------------------------------------------


def test_classify_unmatched_rows_pairs_policy_divergences() -> None:
    only_r = [("philippines r", "cotton", "1933", "100")]
    only_py = [("philippines", "cotton", "1933", "100")]
    report = ComparisonReport("t")
    classify_unmatched_rows(only_r, only_py, COLUMNS, "t.tsv", report)
    assert len(report.accepted) == 1
    assert not report.rejected


def test_classify_unmatched_rows_rejects_a_changed_value() -> None:
    """A float-formatting divergence is not the normalization policy and must not be accepted."""
    only_r = [("indes", "cotton", "1933", "99.9999999999996")]
    only_py = [("indes", "cotton", "1933", "100")]
    report = ComparisonReport("t")
    classify_unmatched_rows(only_r, only_py, COLUMNS, "t.tsv", report)
    assert not report.accepted
    assert len(report.rejected) == 2  # unmatched on both sides


def test_classify_unmatched_rows_matches_one_to_one() -> None:
    """Two R rows collapsing onto one Python row cannot both be excused in a record-valued file."""
    only_r = [
        ("philippines r", "cotton", "1933", "100"),
        ("philippines r r", "cotton", "1933", "100"),
    ]
    only_py = [("philippines", "cotton", "1933", "100")]
    report = ComparisonReport("t")
    classify_unmatched_rows(only_r, only_py, COLUMNS, "t.tsv", report)
    assert len(report.accepted) == 1
    assert len(report.rejected) == 1


def test_classify_set_rows_allows_collapse() -> None:
    """In a unique-value list, an accepted divergence legitimately collapses two entries."""
    r_rows = [("australia",), ("australia r",), ("brazil",)]
    py_rows = [("australia",), ("brazil",)]
    report = ComparisonReport("t")
    classify_set_rows(
        [("australia r",)], [], r_rows, py_rows, ["polity"], "unique_polity.xlsx!s", report
    )
    assert len(report.accepted) == 1
    assert not report.rejected
    assert report.accepted[0].fields == ["polity: 'australia r' -> 'australia'"]


def test_classify_set_rows_picks_the_closest_counterpart() -> None:
    """``asia`` is also a subsequence of ``australia r``; the report must name ``australia``."""
    r_rows = [("australia r",)]
    py_rows = [("asia",), ("australia",)]
    report = ComparisonReport("t")
    classify_set_rows([("australia r",)], [], r_rows, py_rows, ["polity"], "loc", report)
    assert report.accepted[0].fields == ["polity: 'australia r' -> 'australia'"]


def test_classify_set_rows_rejects_an_unexplainable_entry() -> None:
    report = ComparisonReport("t")
    classify_set_rows([("wheat",)], [], [("wheat",)], [("barley",)], ["commodity"], "loc", report)
    assert not report.accepted
    assert len(report.rejected) == 1


# ---------------------------------------------------------------------------
# TSV reading + the value-sum invariant
# ---------------------------------------------------------------------------


def test_read_tsv_handles_crlf(tmp_path: Path) -> None:
    path = tmp_path / "t.tsv"
    path.write_bytes(b"a\tb\r\n1\t2\r\n")
    terminator, header, rows = read_tsv(path)
    assert terminator == "\r\n"
    assert header == ["a", "b"]
    assert rows == [("1", "2")]


def test_read_tsv_handles_lf(tmp_path: Path) -> None:
    path = tmp_path / "t.tsv"
    path.write_bytes(b"a\tb\n1\t2\n")
    terminator, _header, rows = read_tsv(path)
    assert terminator == "\n"
    assert rows == [("1", "2")]


def test_value_sum_is_exact_and_skips_unparseable() -> None:
    rows = [("x", "0.1"), ("x", "0.2"), ("x", ""), ("x", "NA")]
    assert str(value_sum(rows, 1)) == "0.3"  # Decimal, not float: 0.1 + 0.2 == 0.3 exactly


# ---------------------------------------------------------------------------
# End-to-end full-dataset parity (slow; opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parity
def test_full_dataset_parity_against_r() -> None:
    """Python output matches R except the accepted normalization-policy divergence.

    Fails loudly — rather than skipping — when the R oracle or the production dataset is
    missing: this test is opt-in via ``-m slow``, so a silent skip would defeat its purpose.
    """
    try:
        r_project = resolve_r_project()
        outcome = check_parity(
            r_project,
            run_r=False,
            budget=13,
            allow_stale=False,
            keep_output=False,
        )
    except PreconditionError as exc:
        pytest.fail(f"full-dataset parity precondition not met:\n{exc}")

    assert outcome.failures == [], "\n".join(outcome.failures)
