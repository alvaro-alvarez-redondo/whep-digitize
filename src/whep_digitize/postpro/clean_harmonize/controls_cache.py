r"""Postpro / clean_harmonize — multi-pass controls and cycle detection.

* :func:`resolve_stage_multi_pass_controls` — the per-stage multi-pass settings (enabled,
  max_passes, cycle_policy, diagnostics_verbosity) from the centralized constants.
* Cycle detection — two-tier, so repeated states are caught without hashing every pass in full:

  1. A **cheap fingerprint** (row count, plus per-column name, dtype, null count, and total
     UTF-8 byte length). A fingerprint mismatch is conclusive proof that two states differ.
  2. Only when fingerprints match does the comparison fall through to an **exact content hash**
     (``df.hash_rows()`` folded to one digest), which is both order- and column-sensitive.

  Convergence rests mainly on the cheap ``changed_value_count == 0`` early stop in the layer
  runner; this record-and-compare machinery is the safety net for oscillating rule sets.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.utilities.stage_definitions import validate_postpro_stage_name
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ConfigurationError
from whep_digitize.setup.helpers.assertions import require

_CONSTANTS = get_pipeline_constants()
_ContentHash = bytes
# A per-column fingerprint entry: (name, dtype string, null count, total UTF-8 byte length).
_ColumnFingerprint = tuple[str, str, int, int]
_Fingerprint = tuple[int, tuple[_ColumnFingerprint, ...]]


@dataclass(frozen=True, slots=True)
class MultiPassControls:
    """Resolved multi-pass controls for one stage.

    Attributes:
        enabled: Whether multi-pass convergence is enabled for the stage.
        max_passes: Maximum passes when enabled (a single pass otherwise).
        cycle_policy: ``"warn"`` or ``"abort"`` on a detected cycle.
        diagnostics_verbosity: ``"compact"`` or ``"verbose"``.
    """

    enabled: bool
    max_passes: int
    cycle_policy: str
    diagnostics_verbosity: str


@dataclass(frozen=True, slots=True)
class StageStateRecord:
    """A pass-state snapshot for cycle detection: a cheap fingerprint + an exact content hash."""

    fingerprint: _Fingerprint
    content_hash: _ContentHash


def resolve_stage_multi_pass_controls(config: object, stage_name: str) -> MultiPassControls:
    """Resolve the multi-pass controls for a stage from the centralized constants.

    The multi-pass settings are frozen constants rather than per-run configuration, so this
    reads them directly. ``config`` is accepted only to keep the resolver signatures uniform.

    Args:
        config: The pipeline configuration (unused; the settings live in the constants).
        stage_name: The execution stage (``clean`` or ``harmonize``).

    Returns:
        The resolved :class:`MultiPassControls`.

    Raises:
        ValidationError: If the stage name is unsupported.
        ConfigurationError: If the stage lacks an enable / max-pass setting, or the cycle policy
            or diagnostics verbosity is not among the supported values.
    """
    del config  # settings are centralized in the constants, not per-run config
    stage = validate_postpro_stage_name(stage_name)
    multi_pass = _CONSTANTS.postpro.multi_pass

    if stage not in multi_pass.enabled_by_stage or stage not in multi_pass.max_passes_by_stage:
        raise ConfigurationError(f"multi-pass configuration is missing settings for stage: {stage}")
    if multi_pass.cycle_policy not in multi_pass.supported_cycle_policies:
        raise ConfigurationError(f"invalid multi-pass cycle policy: {multi_pass.cycle_policy}")
    if multi_pass.diagnostics_verbosity not in multi_pass.supported_diagnostics_verbosity:
        raise ConfigurationError(
            f"invalid multi-pass diagnostics verbosity: {multi_pass.diagnostics_verbosity}"
        )

    return MultiPassControls(
        enabled=bool(multi_pass.enabled_by_stage[stage]),
        max_passes=int(multi_pass.max_passes_by_stage[stage]),
        cycle_policy=multi_pass.cycle_policy,
        diagnostics_verbosity=multi_pass.diagnostics_verbosity,
    )


def _fingerprint_stage_state(dataset: pl.DataFrame) -> _Fingerprint:
    """Build the cheap fingerprint: row count + per-column (name, dtype, nulls, byte length)."""
    columns: list[_ColumnFingerprint] = []
    for name in dataset.columns:
        column = dataset.get_column(name)
        byte_length = int(column.str.len_bytes().sum() or 0) if column.dtype == pl.String else 0
        columns.append((name, str(column.dtype), column.null_count(), byte_length))
    return (dataset.height, tuple(columns))


def _content_hash(dataset: pl.DataFrame) -> _ContentHash:
    """Fold ``df.hash_rows()`` (order- and column-sensitive) to one deterministic digest."""
    row_hashes = dataset.hash_rows()
    packed = struct.pack(f"<{row_hashes.len()}Q", *row_hashes.to_list())
    return hashlib.blake2b(packed, digest_size=32).digest()


def build_stage_state_record(dataset: pl.DataFrame) -> StageStateRecord:
    """Snapshot a pass state as a cheap fingerprint plus an exact content hash.

    Args:
        dataset: The pass-state dataset.

    Returns:
        The :class:`StageStateRecord` for the state.
    """
    return StageStateRecord(_fingerprint_stage_state(dataset), _content_hash(dataset))


def find_repeated_stage_state_pass(
    state_records: Sequence[StageStateRecord],
    state_pass_indexes: Sequence[int],
    candidate_record: StageStateRecord,
) -> int | None:
    """Return the earliest pass index whose state matches ``candidate_record``, else ``None``.

    Fingerprints screen out definite non-matches cheaply; only a fingerprint match falls through
    to the exact content-hash comparison, so the verdict is as strong as comparing full frame
    contents while rarely paying for it.

    Args:
        state_records: Prior pass-state records.
        state_pass_indexes: Pass indexes aligned with ``state_records``.
        candidate_record: The candidate state.

    Returns:
        The repeated pass index, or ``None`` if the candidate state is new.

    Raises:
        ValidationError: If the record and index sequences differ in length.
    """
    require(
        len(state_records) == len(state_pass_indexes),
        "state-record and pass-index sequences must have equal length",
    )
    for record, pass_index in zip(state_records, state_pass_indexes, strict=True):
        if (
            record.fingerprint == candidate_record.fingerprint
            and record.content_hash == candidate_record.content_hash
        ):
            return pass_index
    return None
