"""Parity test: document-major validation must match the R golden byte-for-byte.

Runs ``validate_long_df_by_document`` over the interleaved multi-document fixture and asserts
the verbatim error strings, their exact order (the 4-key stable sort), and the document-major
reordered data all equal R's ``validate_long_df_by_document`` output. ``current_year`` is pinned
to 2025 to match the R capture's ``Sys.Date`` override, so the plausible-year range in the
messages is deterministic.

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.ingest.output.validate import ValidationResult, validate_long_df_by_document
from whep_digitize.setup.config import load_pipeline_config

_SPEC = GOLDENS["validate"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_PINNED_YEAR = 2025  # matches the R capture's Sys.Date override


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with "
            f"`python tests/parity/capture.py {_SPEC.module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def result() -> ValidationResult:
    records = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    frame = pl.DataFrame(records)
    config = load_pipeline_config(root=FIXTURES_DIR.parents[1])
    return validate_long_df_by_document(frame, config, current_year=_PINNED_YEAR)


@pytest.mark.parity
def test_error_strings_and_order(result: ValidationResult) -> None:
    # Verbatim error text AND order (a downstream consumer compares the text).
    assert list(result.errors) == _gold("errors")


@pytest.mark.parity
def test_document_major_data(result: ValidationResult) -> None:
    assert result.data.get_column("document").to_list() == _gold("data_document")
    assert result.data.get_column("value").to_list() == _gold("data_value")
