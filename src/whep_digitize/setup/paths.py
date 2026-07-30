"""Project-root resolution — the Python equivalent of R's ``here::here()``.

``here::here()`` anchors all pipeline paths at the project root (identified by a marker
such as ``.git`` or a project file). This module reproduces that behavior so ``data/``
is always resolved relative to the repository root, independent of the current working
directory.
"""

from __future__ import annotations

import os
from pathlib import Path

# Markers that identify the project root, in priority order.
_ROOT_MARKERS: tuple[str, ...] = ("pyproject.toml", ".git")

# Environment variable to force a project root (highest priority).
_ROOT_ENV_VAR = "WHEP_PROJECT_ROOT"


def project_root(start: Path | str | None = None) -> Path:
    """Resolve the project root directory.

    Resolution order (first match wins):

    1. The ``WHEP_PROJECT_ROOT`` environment variable, if set.
    2. The nearest ancestor of ``start`` (or the current working directory) that
       contains a root marker (``pyproject.toml`` or ``.git``).
    3. The current working directory (fallback).

    Args:
        start: Directory to begin the upward search from. Defaults to the current
            working directory.

    Returns:
        The resolved project root as an absolute :class:`~pathlib.Path`.
    """
    forced = os.environ.get(_ROOT_ENV_VAR)
    if forced:
        return Path(forced).expanduser().resolve()

    origin = Path(start).resolve() if start is not None else Path.cwd().resolve()
    search_start = origin if origin.is_dir() else origin.parent

    for candidate in (search_start, *search_start.parents):
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate

    return search_start
