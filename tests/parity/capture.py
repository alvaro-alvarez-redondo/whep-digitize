"""CLI to (re)generate R golden files for parity tests.

Goldens live under ``tests/golden/`` and are **committed**: they are the frozen R reference the
parity suite — CI included — compares against, which is why no R install is needed to run it.
Run this only on a deliberate R-reference change, then commit the resulting golden diff together
with the change that motivated it. See ``tests/golden/README.md``.

Usage::

    # from the repo root, with the project venv:
    .venv/Scripts/python.exe tests/parity/capture.py               # all registered captures
    .venv/Scripts/python.exe tests/parity/capture.py file_metadata

Environment: ``WHEP_RSCRIPT`` and ``WHEP_R_REPO`` override the Rscript / R-repo locations
(see :mod:`r_harness`).
"""

from __future__ import annotations

import sys

from r_harness import run_capture
from registry import CAPTURES


def main(argv: list[str]) -> int:
    """Run the requested captures (all of them when no names are given).

    Args:
        argv: Capture module names to run; empty means every registered capture.

    Returns:
        A process exit code (0 on success, 2 on an unknown capture name).
    """
    names = argv or list(CAPTURES)
    unknown = [name for name in names if name not in CAPTURES]
    if unknown:
        print(f"Unknown capture(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Available: {', '.join(CAPTURES)}", file=sys.stderr)
        return 2

    for name in names:
        spec = CAPTURES[name]
        produced = run_capture(spec)
        print(f"[{name}] captured {len(produced)} golden(s):")
        for export, path in produced.items():
            print(f"    {export} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
