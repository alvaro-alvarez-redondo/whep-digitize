"""Parity test: data-audit findings + parsed value must match the frozen reference.

Exercises ``audit_data_output`` over a frozen fixture and
asserts:

* ``run_master_validation`` findings — 1-based ``row_index`` in plan order (``character_non_empty``
  on ``document``, then ``numeric_string`` on ``value``), the verbatim audit type/message strings,
  and the sorted-unique ``invalid_row_index``.
* the audited ``value`` column — ``cast(Float64, strict=False)``: the
  stricter audit regex flags negatives / scientific / signed values that STILL parse, and invalid
  rows are retained (the audited frame keeps every input row).

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.postpro.audit.audit import audit_data_output
from whep_digitize.postpro.audit.validation import run_master_validation
from whep_digitize.setup.config import Config

_SPEC = GOLDENS["data_audit"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_AUDIT_MAP: dict[str, tuple[str, ...]] = {
    "character_non_empty": ("document",),
    "numeric_string": ("value",),
}


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, list[str | None]]:
    data: dict[str, list[str | None]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def _dataset(fixture_data: dict[str, list[str | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "value": pl.Series("value", fixture_data["value"], dtype=pl.String),
            "document": pl.Series("document", fixture_data["document"], dtype=pl.String),
        }
    )


@pytest.mark.parity
def test_findings_match_golden(fixture_data: dict[str, list[str | None]]) -> None:
    result = run_master_validation(_dataset(fixture_data), _AUDIT_MAP)
    findings = result.findings
    assert [str(index) for index in findings.get_column("row_index").to_list()] == _gold(
        "findings_row_index"
    )
    assert findings.get_column("audit_column").to_list() == _gold("findings_audit_column")
    assert findings.get_column("audit_type").to_list() == _gold("findings_audit_type")
    assert findings.get_column("audit_message").to_list() == _gold("findings_audit_message")
    assert [str(index) for index in result.invalid_row_index] == _gold("invalid_row_index")


@pytest.mark.parity
def test_audited_value_parses_with_divergence(
    fixture_data: dict[str, list[str | None]], config: Config
) -> None:
    dataset = _dataset(fixture_data)
    result = audit_data_output(dataset, config, audit_columns_by_type=_AUDIT_MAP)
    # Invalid rows are retained: the audited frame keeps every input row.
    assert result.audited.height == dataset.height
    parsed = result.audited.get_column("value").to_list()
    expected = [None if text is None else float(text) for text in _gold("parsed_value")]
    assert parsed == expected
