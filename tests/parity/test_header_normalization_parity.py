"""Parity test: Python header normalization must match the frozen reference byte-for-byte.

The core check is ``normalize_header_names`` over the frozen header fixture — the ordered regex
chain plus the diacritic fold. Normalization follows the documented NFD diacritic-strip policy
(see ``.claude/docs/pipeline-behaviors.md``), so the fixture holds only inputs whose fold is
unambiguous — accents and diacritics (café, São, Zürich, Ñoño, naïve, Åland, …). Characters with
no ASCII base (``groß``, ``½``, ``œuvre``, ``æsir``, ``Øresund``) are pinned by the policy tests
in ``tests/setup/test_helpers.py``, not here. The renames goldens cover the canonical/alias
collision guards; ``validate_dups`` covers collision detection.

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from goldens import FIXTURES_DIR, GOLDENS

from whep_digitize.ingest.reading.header_normalization import (
    normalize_header_names,
    resolve_canonical_header_renames,
    validate_header_normalization,
)

_SPEC = GOLDENS["header_normalization"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None  # this spec always declares a JSON fixture
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME

# The canonical header set the sheet reader builds.
_CANON = ["continent", "polity", "unit", "footnotes", "commodity", "variable", "hemisphere"]


def _golden(export: str) -> list[str | None]:
    path = _SPEC.golden_paths()[export]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} is missing from the checkout; restore it from version control "
            "(the goldens are frozen and have no regeneration path)."
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.mark.parity
def test_normalize_matches_golden() -> None:
    inputs = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert normalize_header_names(inputs) == _golden("normalize")


@pytest.mark.parity
@pytest.mark.parametrize(
    ("prefix", "raw", "alias_map"),
    [
        ("renames_main", [" Continent ", "Country", "commodity"], None),
        ("renames_guarded", ["Country", "polity"], None),
        (
            "renames_dedup",
            ["Country", "Nation", "Continent"],
            {"country": "polity", "nation": "polity"},
        ),
    ],
)
def test_renames_match_golden(
    prefix: str, raw: list[str], alias_map: Mapping[str, str] | None
) -> None:
    normalized = normalize_header_names(raw)
    result = resolve_canonical_header_renames(raw, normalized, _CANON, alias_map=alias_map)
    assert list(result.old) == _golden(f"{prefix}_old")
    assert list(result.new) == _golden(f"{prefix}_new")


@pytest.mark.parity
def test_validate_detects_same_collisions() -> None:
    # The same input the collision golden was produced from.
    raw = ["A B", "A  B", "a__b", "Foo", "foo", "A-B"]
    normalized = normalize_header_names(raw)
    errors = validate_header_normalization(raw, normalized, "f.xlsx", "Sheet1")
    duplicates = _golden("validate_dups")
    assert len(errors) == 1
    # The message reports exactly the colliding keys, in the golden's order.
    assert errors[0].endswith(": " + ", ".join(str(name) for name in duplicates))
