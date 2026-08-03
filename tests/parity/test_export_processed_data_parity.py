r"""Parity test: the processed-data TSV writer must reproduce the reference bytes exactly.

Builds a harmonize-layer export frame from the frozen fixture (character columns + a
``Float64`` value, matching the post-audit dtype) and asserts
:func:`whep_digitize.export.processed_data.export.write_processed_table` reproduces the exact
reference bytes. The golden is the whole file as a hex string, so this pins every byte-level
divergence a naive ``write_csv(separator="\t")`` would introduce: the auto-quoting rules
(embedded tab / newline / quote, and empty string vs null) and the double formatting (15
significant figures, fixed notation, trailing ``.0`` dropped).

**The record separator is platform-relative, and deliberately so.** The writer emits the
platform newline (``\r\n`` on Windows, ``\n`` elsewhere), so the golden's separators belong to
whichever OS produced it. Comparing the raw bytes would therefore fail purely for running on a
different OS (the goldens were produced on Windows; CI runs Linux).
:func:`_retarget_record_separators` re-terminates the golden's *records* — and only those,
never a newline embedded inside a quoted field — with the eol this platform uses. The
comparison stays byte-exact and still pins the eol convention itself: a writer that emitted
``\n`` on Windows (or ``\r\n`` on Linux) fails here.
The expected eol is derived independently from :data:`os.name`, never imported from the module
under test, so the assertion cannot go tautological.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.export.processed_data import export as export_module
from whep_digitize.export.processed_data.export import write_processed_table

_SPEC = GOLDENS["export_processed_data"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME

# The expected record separator for this platform. Mirrors — but is intentionally independent
# of — ``export._FWRITE_EOL``, so the assertion cannot go tautological.
_PLATFORM_EOL = b"\r\n" if os.name == "nt" else b"\n"

# The golden was produced with this column order; the frame must match it (columns are emitted
# in frame order). `value` is the only numeric column.
_COLUMN_ORDER = [
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "value",
    "notes",
    "footnotes",
    "yearbook",
    "document",
]


def _retarget_record_separators(data: bytes, eol: bytes) -> bytes:
    r"""Re-terminate every record of an RFC 4180-style delimited file with ``eol``.

    Walks the bytes tracking quote state and rewrites ``\r\n`` / ``\n`` only where it is a
    record separator. A newline inside a quoted field is *data* (the writer quotes any field
    containing one) and is copied through untouched — which is why a blind
    ``replace(b"\n", b"\r\n")`` cannot be used here. Quote state toggles on every ``"``, so
    the doubled-quote escape (``""``) toggles twice and leaves the state correct.

    Args:
        data: The captured file bytes.
        eol: The record separator to emit (``b"\r\n"`` or ``b"\n"``).

    Returns:
        ``data`` with every record separator replaced by ``eol``; all other bytes preserved.
    """
    out = bytearray()
    in_quotes = False
    index = 0
    size = len(data)
    while index < size:
        byte = data[index : index + 1]
        if byte == b'"':
            in_quotes = not in_quotes
            out += byte
            index += 1
        elif not in_quotes and byte in (b"\r", b"\n"):
            index += 2 if data[index : index + 2] == b"\r\n" else 1
            out += eol
        else:
            out += byte
            index += 1
    return bytes(out)


def _golden_bytes() -> bytes:
    path = _SPEC.golden_paths()["tsv_hex"]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    hex_string: list[str] = json.loads(path.read_text(encoding="utf-8"))
    return bytes.fromhex(hex_string[0])


@pytest.fixture(scope="module")
def export_frame() -> pl.DataFrame:
    """The fixture as an export frame: all columns String except ``value`` (Float64)."""
    records = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    columns: dict[str, pl.Series] = {}
    for name in _COLUMN_ORDER:
        series = pl.Series(name, [record[name] for record in records], dtype=pl.String)
        if name == "value":
            # `value` is parsed to Float64 by the audit stage; String -> Float64 matches.
            series = series.cast(pl.Float64, strict=False)
        columns[name] = series
    return pl.DataFrame(columns).select(_COLUMN_ORDER)


@pytest.mark.parity
def test_write_processed_table_matches_reference_bytes(
    export_frame: pl.DataFrame, tmp_path: Path
) -> None:
    assert export_frame.schema["value"] == pl.Float64  # the numeric-formatting path is exercised
    expected = _retarget_record_separators(_golden_bytes(), _PLATFORM_EOL)
    assert _PLATFORM_EOL in expected  # the eol convention is pinned, not normalized away
    output_path = write_processed_table(export_frame, tmp_path / "whep_data_harmonize.tsv")
    assert output_path.read_bytes() == expected


@pytest.mark.parity
@pytest.mark.parametrize("eol", [b"\r\n", b"\n"], ids=["windows", "unix"])
def test_write_processed_table_matches_reference_under_both_platform_eols(
    export_frame: pl.DataFrame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, eol: bytes
) -> None:
    """Both eol conventions are pinned, whichever OS is running.

    The test above can only exercise the eol of the host it runs on, which would leave a
    byte divergence on the *other* OS hidden until that OS ran CI. Overriding the writer's
    platform constant covers both from anywhere:
    on Windows this proves the Linux CI bytes, and vice versa.
    """
    monkeypatch.setattr(export_module, "_FWRITE_EOL", eol.decode("ascii"))
    expected = _retarget_record_separators(_golden_bytes(), eol)
    output_path = write_processed_table(export_frame, tmp_path / "whep_data_harmonize.tsv")
    assert output_path.read_bytes() == expected


def test_retarget_record_separators_preserves_embedded_newlines() -> None:
    """The retargeting must rewrite record separators only, never quoted-field content."""
    # One header record + one data record whose last field embeds a newline and a doubled quote.
    windows = b'a\tb\r\nx\t"line1\nline2"\r\ny\t"say ""hi"""\r\n'
    unix = b'a\tb\nx\t"line1\nline2"\ny\t"say ""hi"""\n'

    assert _retarget_record_separators(windows, b"\n") == unix
    assert _retarget_record_separators(unix, b"\r\n") == windows
    # Idempotent when the target eol already matches, on either platform's capture.
    assert _retarget_record_separators(windows, b"\r\n") == windows
    assert _retarget_record_separators(unix, b"\n") == unix


def test_retarget_record_separators_changes_only_separators_of_golden() -> None:
    """Retargeting the real golden rewrites its separators and nothing else."""
    golden = _golden_bytes()
    assert b"\x00" not in golden  # NUL is free to use as an unambiguous split sentinel
    records = _retarget_record_separators(golden, b"\x00").split(b"\x00")
    assert len(records) > 1  # the golden really is multi-record

    # Whatever eol is targeted, the result is exactly those same records rejoined — so no field
    # byte (including the newline embedded in a quoted `notes` value) is ever touched.
    for eol in (b"\r\n", b"\n"):
        assert _retarget_record_separators(golden, eol) == eol.join(records)
