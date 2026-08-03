"""Guard: every registered capture's golden must exist in the checkout.

Goldens under ``tests/golden/`` are committed — they are the frozen R reference, and committing
them is what lets the parity suite run in CI without an R install (see ``tests/golden/README.md``).
A missing golden therefore means a broken or stale checkout, not "no R here".

This guard exists because the individual parity tests degrade *silently*: each one calls
``pytest.skip`` when its golden is absent, so an absent golden set turns the whole parity suite
green while it compares nothing — precisely the hole that let R-parity regressions through CI
while the goldens were gitignored. This test fails loudly in that situation, per module.
"""

from __future__ import annotations

import pytest
from goldens import GOLDENS


@pytest.mark.parity
@pytest.mark.parametrize("module", sorted(GOLDENS))
def test_module_goldens_are_present(module: str) -> None:
    spec = GOLDENS[module]
    missing = sorted(str(path) for path in spec.golden_paths().values() if not path.is_file())
    assert not missing, (
        f"{len(missing)} golden(s) missing for '{module}' — the parity tests that use them would "
        f"skip silently. Restore them from git, or regenerate with "
        f"`python tests/parity/capture.py {module}`:\n  " + "\n  ".join(missing)
    )
