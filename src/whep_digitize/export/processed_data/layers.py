"""Layer-table detection for export.

Exportable tables are selected *by name*: a table whose name ends in a configured layer suffix
(``_raw`` / ``_clean`` / ``_normalize`` / ``_harmonize``) is included, except for ``_wide_raw``
and ``_post_processed``, which are always excluded. Candidates are passed in explicitly as a
mapping of object name to frame, so no type check is needed: every value is already a frame.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import polars as pl

from whep_digitize.setup.errors import ValidationError

# Default value of the ``layer_suffixes`` argument.
_DEFAULT_LAYER_SUFFIXES: tuple[str, ...] = ("raw", "clean", "normalize", "harmonize")
# Suffixes that are excluded even though they end in a layer suffix (``_wide_raw`` ends in
# ``_raw``; ``_post_processed`` is a diagnostics bag). Both are checked explicitly.
_EXCLUDED_SUFFIXES: tuple[str, ...] = ("_post_processed", "_wide_raw")


def collect_layer_tables_for_export(
    data_objects: Mapping[str, pl.DataFrame],
    layer_suffixes: Sequence[str] = _DEFAULT_LAYER_SUFFIXES,
) -> dict[str, pl.DataFrame]:
    """Select the layer tables eligible for export, keyed and sorted by object name.

    A name is valid when it is non-empty, ends in one of ``layer_suffixes`` (``_<suffix>``), and
    does **not** end in ``_post_processed`` or ``_wide_raw``. The result is ordered by name
    (code-point sort, so the order never depends on the ambient locale).

    Args:
        data_objects: Mapping of object name to its frame (e.g. ``{"whep_data_harmonize": ...}``).
        layer_suffixes: Supported layer suffixes; must be non-empty and unique.

    Returns:
        A new ``dict`` of the valid tables, ordered by name.

    Raises:
        ValidationError: If ``layer_suffixes`` is empty or has duplicates, or if no object
            name matches ("no layer tables detected for export").
    """
    if not layer_suffixes:
        raise ValidationError("layer_suffixes must contain at least one suffix")
    if len(set(layer_suffixes)) != len(layer_suffixes):
        raise ValidationError("layer_suffixes must be unique")

    layer_pattern = re.compile(
        r"_(" + "|".join(re.escape(suffix) for suffix in layer_suffixes) + r")$"
    )
    detected = {
        name: frame
        for name, frame in data_objects.items()
        if _is_valid_layer_name(name, layer_pattern)
    }

    if not detected:
        raise ValidationError(
            "no layer tables detected for export: expected object names ending in one of "
            f"{tuple(layer_suffixes)} (excluding {_EXCLUDED_SUFFIXES})"
        )

    return {name: detected[name] for name in sorted(detected)}


def _is_valid_layer_name(object_name: str, layer_pattern: re.Pattern[str]) -> bool:
    """Return whether an object name selects a layer table."""
    if not object_name:
        return False
    if layer_pattern.search(object_name) is None:
        return False
    return not any(object_name.endswith(excluded) for excluded in _EXCLUDED_SUFFIXES)
