"""Column resolution and identical-layer merging.

Resolves which configured columns are exportable and groups the four layers (``raw`` / ``clean``
/ ``normalize`` / ``harmonize``) so that layers with an identical value-set share one merged
sheet (e.g. ``raw_clean_normalize_harmonize``). The inputs are the deterministic per-layer value
lists from :func:`~whep_digitize.export.lists.unique_values.compute_unique_column_values`, so a
plain list equality *is* a set comparison here: both sides are already deduplicated and carry
the same code-point order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from whep_digitize.export.lists.unique_values import LISTS_SHEET_ORDER
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError


def resolve_lists_export_columns(config: Config, union_columns: Sequence[str]) -> list[str]:
    """Return the configured list columns present across the detected layers, in config order.

    Intersects ``config.output_config.lists_to_export`` with ``union_columns``, preserving the
    configured order.

    Args:
        config: The resolved pipeline configuration.
        union_columns: The columns detected across all layers.

    Returns:
        The columns to export, in configured order.

    Raises:
        ValidationError: If ``lists_to_export`` is empty/duplicated, or none of the configured
            columns are present in the detected layers.
    """
    configured = config.output_config.lists_to_export
    if not configured:
        raise ValidationError(
            "config.output_config.lists_to_export must be defined for list export"
        )
    if len(set(configured)) != len(configured):
        raise ValidationError("config.output_config.lists_to_export must be unique")

    present = set(union_columns)
    export_columns = [column for column in configured if column in present]
    if not export_columns:
        raise ValidationError(
            "lists export failed: none of the configured columns are present in detected layers "
            f"(configured {tuple(configured)}, detected {tuple(union_columns)})"
        )
    return export_columns


def resolve_list_sheet_payloads(
    layer_values: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    """Group layers with identical value-sets into merged sheets, preserving fixed order.

    Iterates the layers in :data:`LISTS_SHEET_ORDER`, joining each to the first existing group
    whose representative has an identical value list, or opening a new group. A group's sheet name
    is its layer names joined by ``_`` (e.g. ``"clean_normalize_harmonize"``) and its payload is
    the representative (first) layer's values.

    Args:
        layer_values: The per-layer value lists, keyed by the four layer labels.

    Returns:
        An ordered mapping of sheet name -> the sheet's values.
    """
    groups: list[list[str]] = []
    for layer in LISTS_SHEET_ORDER:
        current = list(layer_values[layer])
        matched = next((group for group in groups if list(layer_values[group[0]]) == current), None)
        if matched is None:
            groups.append([layer])
        else:
            matched.append(layer)

    return {"_".join(group): list(layer_values[group[0]]) for group in groups}
