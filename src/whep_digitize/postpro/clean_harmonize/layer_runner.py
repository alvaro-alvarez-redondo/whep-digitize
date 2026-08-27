r"""Postpro / clean_harmonize — the multi-pass rule-stage driver.

:func:`run_rule_stage_layer_batch` plus the :func:`run_cleaning_layer_batch` /
:func:`run_harmonize_layer_batch` entry points — the algorithmic core of the clean and harmonize
stages.

For a stage it loads the coerced rule payloads (from
:mod:`whep_digitize.postpro.utilities.payload_cache`), validates each against the dataset once,
then iterates rule-application passes (max 10). Each pass applies every payload via
``apply_rule_payload`` and accumulates the change count. The multi-pass contract:

* stop when a pass changes nothing (``changed_value_count == 0`` → converged);
* stop when a pass reproduces an earlier pass state (cycle → warn or abort per the configured
  cycle policy);
* stop when the pass limit is hit (warn).

Match-key normalization runs on pass 1 only (the centralized default). After the loop the
``;``-annotation columns are canonicalized and an all-missing ``footnotes`` column is dropped.

Results are returned as a typed :class:`StageLayerResult`. State comparison for cycle detection
uses the deterministic content hash in
:mod:`whep_digitize.postpro.clean_harmonize.controls_cache`.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import polars as pl

from whep_digitize.contracts import LayerDiagnostics, MultiPassDiagnostics
from whep_digitize.postpro.clean_harmonize.controls_cache import (
    build_stage_state_record,
    find_repeated_stage_state_pass,
    resolve_stage_multi_pass_controls,
)
from whep_digitize.postpro.clean_harmonize.stage_inputs import (
    canonicalize_post_loop_annotation_columns,
    drop_empty_footnotes_column,
)
from whep_digitize.postpro.rule_engine.matching_strategy import (
    empty_last_rule_wins_overwrite_events_df,
    resolve_rule_match_normalization_settings,
)
from whep_digitize.postpro.rule_engine.payload_application import apply_rule_payload
from whep_digitize.postpro.rule_engine.schema_validation import (
    ensure_rule_referenced_columns,
    validate_canonical_rules,
)
from whep_digitize.postpro.utilities.diagnostics import build_layer_diagnostics
from whep_digitize.postpro.utilities.payload_cache import get_cached_stage_payload_bundle
from whep_digitize.postpro.utilities.stage_definitions import validate_postpro_stage_name
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import WhepError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.frames import canonicalize_semicolon_string_columns

_CONSTANTS = get_pipeline_constants()
_DEFAULT_DATASET_NAME = _CONSTANTS.dataset_default_name
_TIMESTAMP_FORMAT = _CONSTANTS.timestamp_format_utc
_FOOTNOTES = "footnotes"
_AFFECTED_ROWS = "affected_rows"
_PASS_DIAGNOSTICS_SCHEMA: dict[str, type[pl.DataType]] = {
    "pass_index": pl.Int64,
    "changed_value_count": pl.Int64,
    "matched_count": pl.Int64,
    "audit_rows": pl.Int64,
    "overwrite_event_rows": pl.Int64,
    "repeated_state_pass": pl.Int64,
    "stop_reason": pl.String,
}


@dataclass(frozen=True, slots=True)
class StageLayerResult:
    """Result of one rule-stage layer batch.

    Attributes:
        data: The transformed stage dataset (converged, annotations canonicalized).
        diagnostics: The layer diagnostics, including the :class:`MultiPassDiagnostics`.
        audit: The combined per-rule audit across all passes.
        overwrite_events: The combined last-rule-wins overwrite diagnostics across all passes.
        pass_diagnostics: One row per executed pass (counts + stop reason).
    """

    data: pl.DataFrame
    diagnostics: LayerDiagnostics
    audit: pl.DataFrame
    overwrite_events: pl.DataFrame
    pass_diagnostics: pl.DataFrame


def run_rule_stage_layer_batch(
    dataset: pl.DataFrame,
    config: Config,
    stage_name: str,
    *,
    dataset_name: str = _DEFAULT_DATASET_NAME,
    execution_timestamp_utc: str | None = None,
) -> StageLayerResult:
    """Run a stage's rule payloads to convergence over the multi-pass loop.

    Rules are validated against the dataset once up front, before any pass runs, so a malformed
    rule file fails before the frame has been touched.

    Args:
        dataset: The input stage dataset.
        config: The resolved pipeline configuration (locates rule payloads).
        stage_name: The execution stage (``clean`` or ``harmonize``).
        dataset_name: Dataset identifier (audit / event metadata).
        execution_timestamp_utc: Audit timestamp; generated (UTC now) when ``None``.

    Returns:
        The :class:`StageLayerResult` for the stage.

    Raises:
        WhepError: If a cycle is detected and the cycle policy is ``"abort"``.
    """
    stage = validate_postpro_stage_name(stage_name)
    require(len(dataset_name) >= 1, "dataset_name must be a non-empty string")

    timestamp = execution_timestamp_utc or datetime.now(UTC).strftime(_TIMESTAMP_FORMAT)
    canonical_payloads = get_cached_stage_payload_bundle(config, stage).canonical_payloads
    normalization = resolve_rule_match_normalization_settings()

    footnotes_all_na = (
        _FOOTNOTES not in dataset.columns
        or dataset.get_column(_FOOTNOTES).null_count() == dataset.height
    )

    working = dataset
    for payload in canonical_payloads:
        working = ensure_rule_referenced_columns(working, payload.canonical_rules)
        validate_canonical_rules(
            payload.canonical_rules, working, payload.rule_file_id, stage, payload.rule_file_path
        )

    controls = resolve_stage_multi_pass_controls(config, stage)
    max_passes = controls.max_passes if controls.enabled else 1

    all_pass_audits: list[pl.DataFrame] = []
    all_pass_overwrites: list[pl.DataFrame] = []
    per_pass_rows: list[dict[str, int | str | None]] = []

    converged = cycle_detected = max_reached = False
    cycle_message: str | None = None
    max_passes_message: str | None = None
    stop_reason = "converged_zero_change" if controls.enabled else "single_pass_completed"

    state_records = [build_stage_state_record(working)] if controls.enabled else []
    state_pass_indexes = [0] if controls.enabled else []

    for pass_index in range(1, max_passes + 1):
        apply_normalization = normalization.apply_each_pass or (
            normalization.apply_once_before_stage and pass_index == 1
        )
        pass_data = working
        pass_audits: list[pl.DataFrame] = []
        pass_overwrites: list[pl.DataFrame] = []
        pass_changed = 0
        for payload in canonical_payloads:
            if payload.canonical_rules.height == 0:
                continue
            result = apply_rule_payload(
                pass_data,
                payload.canonical_rules,
                stage,
                dataset_name,
                payload.rule_file_id,
                timestamp,
                apply_match_normalization=apply_normalization,
            )
            pass_data = result.data
            pass_audits.append(result.audit)
            pass_changed += result.changed_value_count
            if result.overwrite_events.height > 0:
                pass_overwrites.append(result.overwrite_events)

        pass_audit = _combine_audit(pass_audits)
        if pass_audit.width > 0:
            pass_audit = pass_audit.with_columns(pl.lit(pass_index, dtype=pl.Int64).alias("loop"))
        pass_overwrite = (
            pl.concat(pass_overwrites, how="diagonal")
            if pass_overwrites
            else empty_last_rule_wins_overwrite_events_df()
        )
        pass_matched = (
            int(pass_audit.get_column(_AFFECTED_ROWS).sum() or 0)
            if _AFFECTED_ROWS in pass_audit.columns
            else 0
        )

        pass_stop = "continued"
        repeated_pass: int | None = None
        if controls.enabled:
            if pass_changed == 0:
                repeated_pass = pass_index - 1
                converged = True
                pass_stop = stop_reason = "converged_zero_change"
            else:
                record = build_stage_state_record(pass_data)
                repeated_pass = find_repeated_stage_state_pass(
                    state_records, state_pass_indexes, record
                )
                if repeated_pass is None:
                    state_records.append(record)
                    state_pass_indexes.append(pass_index)
                elif repeated_pass == pass_index - 1:
                    converged = True
                    pass_stop = stop_reason = "converged_zero_change"
                else:
                    cycle_detected = True
                    pass_stop = stop_reason = "cycle_detected"
                    cycle_message = (
                        f"[{stage} stage] cycle detected at pass {pass_index} "
                        f"(repeats pass {repeated_pass})."
                    )
                    if controls.cycle_policy == "abort":
                        raise WhepError(
                            f"Post-processing multi-pass cycle detected. {cycle_message}"
                        )
                    warnings.warn(cycle_message, stacklevel=2)

        is_final_pass = pass_index >= max_passes
        if controls.enabled and pass_stop == "continued" and is_final_pass:
            max_reached = True
            pass_stop = stop_reason = "max_passes_reached"
            max_passes_message = (
                f"[{stage} stage] reached max_passes={max_passes} before convergence."
            )
            warnings.warn(max_passes_message, stacklevel=2)
        elif not controls.enabled and pass_stop == "continued" and is_final_pass:
            pass_stop = stop_reason = "single_pass_completed"

        per_pass_rows.append(
            {
                "pass_index": pass_index,
                "changed_value_count": pass_changed,
                "matched_count": pass_matched,
                "audit_rows": pass_audit.height,
                "overwrite_event_rows": pass_overwrite.height,
                "repeated_state_pass": repeated_pass,
                "stop_reason": pass_stop,
            }
        )
        all_pass_audits.append(pass_audit)
        if pass_overwrite.height > 0:
            all_pass_overwrites.append(pass_overwrite)
        working = pass_data
        if pass_stop != "continued":
            break

    working = canonicalize_post_loop_annotation_columns(working)
    working = canonicalize_semicolon_string_columns(working)
    if footnotes_all_na:
        working = drop_empty_footnotes_column(working)

    stage_audit = _combine_audit(all_pass_audits)
    stage_overwrite = (
        pl.concat(all_pass_overwrites, how="diagonal")
        if all_pass_overwrites
        else empty_last_rule_wins_overwrite_events_df()
    )
    pass_diagnostics = (
        pl.DataFrame(per_pass_rows, schema=_PASS_DIAGNOSTICS_SCHEMA)
        if per_pass_rows
        else pl.DataFrame(schema=_PASS_DIAGNOSTICS_SCHEMA)
    )

    passes_executed = len(per_pass_rows)
    base = build_layer_diagnostics(stage, dataset.height, working.height, stage_audit)
    multi_pass = MultiPassDiagnostics(
        enabled=controls.enabled,
        max_passes=max_passes,
        passes_executed=passes_executed,
        converged=converged,
        cycle_detected=cycle_detected,
        max_passes_reached_before_convergence=max_reached,
        cycle_policy=controls.cycle_policy,
        diagnostics_verbosity=controls.diagnostics_verbosity,
        stop_reason=stop_reason,
    )
    summary = (
        f"[{stage} stage] multi-pass stop_reason={stop_reason}; "
        f"passes_executed={passes_executed}; max_passes={max_passes}; "
        f"enabled={str(controls.enabled).lower()}."
    )
    messages = (*base.messages, summary)
    if cycle_message is not None:
        messages = (*messages, cycle_message)
    if max_passes_message is not None:
        messages = (*messages, max_passes_message)
    diagnostics = replace(base, messages=messages, multi_pass=multi_pass)
    return StageLayerResult(working, diagnostics, stage_audit, stage_overwrite, pass_diagnostics)


def run_cleaning_layer_batch(
    dataset: pl.DataFrame,
    config: Config,
    *,
    dataset_name: str = _DEFAULT_DATASET_NAME,
    execution_timestamp_utc: str | None = None,
) -> StageLayerResult:
    """Run the ``clean`` stage layer batch."""
    return run_rule_stage_layer_batch(
        dataset,
        config,
        "clean",
        dataset_name=dataset_name,
        execution_timestamp_utc=execution_timestamp_utc,
    )


def run_harmonize_layer_batch(
    dataset: pl.DataFrame,
    config: Config,
    *,
    dataset_name: str = _DEFAULT_DATASET_NAME,
    execution_timestamp_utc: str | None = None,
) -> StageLayerResult:
    """Run the ``harmonize`` stage layer batch."""
    return run_rule_stage_layer_batch(
        dataset,
        config,
        "harmonize",
        dataset_name=dataset_name,
        execution_timestamp_utc=execution_timestamp_utc,
    )


def _combine_audit(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Row-bind the schema-bearing audit frames; return an empty frame when there are none."""
    schema_bearing = [frame for frame in frames if frame.width > 0]
    if not schema_bearing:
        return pl.DataFrame()
    return pl.concat(schema_bearing, how="diagonal")
