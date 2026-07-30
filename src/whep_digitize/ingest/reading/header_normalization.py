"""Header normalization — the Python port of ``11-header-normalization.R``.

Three functions:

* :func:`normalize_header_names` — the ordered normalization chain (trim -> collapse
  whitespace -> strip separator padding -> diacritic-strip + lowercase transliterate ->
  punctuation to ``_`` -> collapse ``_`` -> trim ``_``), with the R fast-path short-circuit
  for already-clean headers. The transliteration is the shared
  :func:`whep_digitize.setup.helpers.strings.transliterate_ascii_lower` (the policy's NFD
  diacritic strip, not R's ICU ``Latin-ASCII``) so header keys and match keys fold identically.
* :func:`resolve_canonical_header_renames` — maps normalized headers to canonical column
  names plus the ``country`` -> ``polity`` alias, with the R collision guards
  (already-exact, target-present, alias source already renamed, duplicate alias targets).
* :func:`validate_header_normalization` — detects collisions created by normalization.

The regex chain, replacements, patterns, and alias map all come from
``get_pipeline_constants()`` (mirrors the R constants). R source:
``r/1-import_pipeline/11-reading/11-header-normalization.R``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.strings import transliterate_ascii_lower

_constants = get_pipeline_constants()
_patterns = _constants.patterns
_replacements = _constants.header_normalization

_WHITESPACE = re.compile(_patterns.header_normalize_whitespace)
_SEPARATOR_SPACING = re.compile(_patterns.header_normalize_separator_spacing)
_NON_ALNUM = re.compile(_patterns.header_normalize_non_alnum)
_MULTI_UNDERSCORE = re.compile(_patterns.header_normalize_multi_underscore)
_TRIM_UNDERSCORE = re.compile(_patterns.header_normalize_trim_underscore)
_FAST_PATH = re.compile(_patterns.header_normalize_fast_path)

_WHITESPACE_REPL = _replacements.whitespace_replacement
_SEPARATOR_REPL = _replacements.separator_replacement
_NON_ALNUM_REPL = _replacements.non_alnum_replacement
_TRIM_UNDERSCORE_REPL = _replacements.trim_underscore_replacement


@dataclass(frozen=True, slots=True)
class HeaderRenames:
    """Parallel old/new column-name vectors for a rename (R ``list(old, new)``).

    ``old[i]`` is the raw header to rename to ``new[i]``. Build a polars rename mapping
    with ``dict(zip(renames.old, renames.new))``.
    """

    old: tuple[str, ...]
    new: tuple[str, ...]


def normalize_header_name(name: str) -> str:
    """Apply the ordered header-normalization chain to a single name.

    Order (must match R exactly): trim both ends -> collapse whitespace runs to a single
    space -> strip whitespace padding around ``/`` and ``-`` -> transliterate to ASCII and
    lowercase -> replace runs of remaining non-``[a-z0-9-/]`` with ``_`` -> collapse ``_``
    runs -> trim leading/trailing ``_``.

    Args:
        name: A single raw header name.

    Returns:
        The normalized header key (may be empty if the name held no alphanumerics).
    """
    result = name.strip()
    result = _WHITESPACE.sub(_WHITESPACE_REPL, result)
    result = _SEPARATOR_SPACING.sub(_SEPARATOR_REPL, result)
    result = transliterate_ascii_lower(result)
    result = _NON_ALNUM.sub(_NON_ALNUM_REPL, result)
    result = _MULTI_UNDERSCORE.sub(_NON_ALNUM_REPL, result)
    result = _TRIM_UNDERSCORE.sub(_TRIM_UNDERSCORE_REPL, result)
    return result


def normalize_header_names(header_names: Sequence[str | None]) -> list[str | None]:
    """Normalize a vector of header names for canonical matching.

    ``None`` (R ``NA``) entries pass through unchanged. Reproduces the R fast-path: when
    every non-null header already matches the clean pattern and none carry collapsible or
    leading/trailing underscores, the input is returned verbatim.

    Args:
        header_names: Raw header names (``None`` allowed).

    Returns:
        A new list of normalized keys, ``None`` preserved positionally.
    """
    result: list[str | None] = list(header_names)
    non_null = [name for name in result if name is not None]
    if not non_null:
        return result

    if all(_FAST_PATH.search(name) for name in non_null):
        has_multi_underscore = any(_MULTI_UNDERSCORE.search(name) for name in non_null)
        has_trim_underscore = any(_TRIM_UNDERSCORE.search(name) for name in non_null)
        if not has_multi_underscore and not has_trim_underscore:
            return result

    return [None if name is None else normalize_header_name(name) for name in result]


def validate_header_normalization(
    header_names: Sequence[str | None],
    normalized_header_names: Sequence[str | None],
    file_path: str,
    sheet_name: str,
) -> list[str]:
    """Detect collisions created by header normalization.

    Args:
        header_names: The raw header names.
        normalized_header_names: The output of :func:`normalize_header_names` (same length).
        file_path: Path to the workbook being read (only its base name is reported).
        sheet_name: Worksheet name.

    Returns:
        A list with a single collision-error message, or an empty list when the normalized
        headers are collision-free. The message content mirrors R (sheet, file, colliding
        keys); its cli box formatting is intentionally not reproduced (errors use the
        Python messaging convention).

    Raises:
        ValidationError: If the two header vectors differ in length or the path / sheet name
            is blank (R ``checkmate`` guards).
    """
    require(
        len(header_names) == len(normalized_header_names),
        "header_names and normalized_header_names must have equal length",
    )
    require(len(file_path) >= 1, "file_path must be a non-empty string")
    require(len(sheet_name) >= 1, "sheet_name must be a non-empty string")

    normalized_valid = [name for name in normalized_header_names if name is not None and name != ""]
    if not normalized_valid:
        return []

    counts = Counter(normalized_valid)
    duplicates = [name for name in dict.fromkeys(normalized_valid) if counts[name] > 1]
    if not duplicates:
        return []

    basename = PurePosixPath(file_path).name
    message = (
        f"normalized header collision detected in sheet '{sheet_name}' "
        f"for file '{basename}': {', '.join(duplicates)}"
    )
    return [message]


def resolve_canonical_header_renames(
    header_names: Sequence[str | None],
    normalized_header_names: Sequence[str | None],
    canonical_names: Sequence[str | None],
    alias_map: Mapping[str, str] | None = None,
) -> HeaderRenames:
    """Map normalized headers to canonical column names, with alias + collision guards.

    A canonical name claims the raw header whose normalized form equals the canonical name's
    normalized form, unless the canonical name is already present verbatim (``has_exact``).
    Aliases (default ``{"country": "polity"}``) then map their normalized source to a raw
    header, but only when: the alias target is itself a canonical name; the target is not
    already a raw header or an already-claimed canonical target; the alias source was not
    already renamed by the canonical pass; and no earlier surviving alias claimed the same
    target (``duplicated`` guard). Renames where ``old == new`` are dropped.

    Args:
        header_names: The raw header names.
        normalized_header_names: The output of :func:`normalize_header_names` (same length).
        canonical_names: Canonical pipeline column names to resolve toward.
        alias_map: Alias source -> canonical target map; defaults to the constants' aliases.

    Returns:
        A :class:`HeaderRenames` with parallel ``old`` / ``new`` vectors (empty when nothing
        renames), suitable for ``dict(zip(old, new))``.

    Raises:
        ValidationError: If ``header_names`` and ``normalized_header_names`` differ in length.
    """
    require(
        len(header_names) == len(normalized_header_names),
        "header_names and normalized_header_names must have equal length",
    )

    canonical = [name for name in dict.fromkeys(canonical_names) if name is not None and name != ""]
    if not canonical:
        return HeaderRenames(old=(), new=())

    # First raw header for each distinct normalized key (R match() first-occurrence index).
    first_raw_by_normalized: dict[str, str] = {}
    for raw, normalized in zip(header_names, normalized_header_names, strict=True):
        if normalized is not None and raw is not None and normalized not in first_raw_by_normalized:
            first_raw_by_normalized[normalized] = raw

    header_set = set(header_names)
    canonical_norm = normalize_header_names(canonical)

    old_names: list[str] = []
    new_names: list[str] = []
    for canonical_name, canonical_key in zip(canonical, canonical_norm, strict=True):
        if canonical_name in header_set:  # has_exact_name -> already present, skip
            continue
        matched_raw = first_raw_by_normalized.get(canonical_key) if canonical_key else None
        if matched_raw is not None:
            old_names.append(matched_raw)
            new_names.append(canonical_name)

    _apply_alias_renames(
        header_names=header_names,
        canonical=canonical,
        first_raw_by_normalized=first_raw_by_normalized,
        old_names=old_names,
        new_names=new_names,
        alias_map=alias_map,
    )

    pairs = [(old, new) for old, new in zip(old_names, new_names, strict=True) if old != new]
    return HeaderRenames(old=tuple(old for old, _ in pairs), new=tuple(new for _, new in pairs))


def _apply_alias_renames(
    *,
    header_names: Sequence[str | None],
    canonical: list[str],
    first_raw_by_normalized: dict[str, str],
    old_names: list[str],
    new_names: list[str],
    alias_map: Mapping[str, str] | None,
) -> None:
    """Append alias renames to ``old_names`` / ``new_names`` in place (R alias pass)."""
    if alias_map is None:
        alias_map = get_pipeline_constants().header_normalization.canonical_aliases

    canonical_set = set(canonical)
    # Valid, non-empty aliases whose target is a canonical name (R filters).
    alias_pairs = [
        (source, target)
        for source, target in alias_map.items()
        if source and target and target in canonical_set
    ]
    if not alias_pairs:
        return

    alias_sources = [source for source, _ in alias_pairs]
    alias_targets = [target for _, target in alias_pairs]
    alias_norm = normalize_header_names(alias_sources)

    # rename_mask: alias matched a raw header AND its target is not already present.
    target_pool = set(header_names) | set(new_names)
    surviving_old: list[str] = []
    surviving_new: list[str] = []
    for source_key, target in zip(alias_norm, alias_targets, strict=True):
        if target in target_pool:
            continue  # target_present -> NA
        matched_raw = first_raw_by_normalized.get(source_key) if source_key else None
        if matched_raw is None:
            continue  # no header matched -> NA
        surviving_old.append(matched_raw)
        surviving_new.append(target)

    # alias_keep = source not already renamed by the canonical pass AND target not a
    # duplicate among surviving aliases (duplicated() is over the full surviving vector).
    canonical_old_set = set(old_names)
    seen_targets: set[str] = set()
    for old_value, new_value in zip(surviving_old, surviving_new, strict=True):
        is_duplicate_target = new_value in seen_targets
        seen_targets.add(new_value)
        if old_value not in canonical_old_set and not is_duplicate_target:
            old_names.append(old_value)
            new_names.append(new_value)
