"""Per-rule-file payload orchestration.

(``prepare_rule_payload_execution_plan`` + ``apply_rule_payload``). For one rule file's canonical
rules it builds the conditional dictionary for deterministic group order, then applies each
conditional group in turn (see :mod:`whep_digitize.postpro.rule_engine.conditional_group`),
accumulating the audit, overwrite events, change count, and changed columns.

Every column runs through the one element-wise engine -- ``footnotes`` included. There is no
separate footnote path: a footnote rule is just a rule whose source column is ``footnotes``.

Every applier is functional and returns a new frame; this module composes them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from whep_digitize.postpro.rule_engine.conditional_group import apply_conditional_rule_group
from whep_digitize.postpro.rule_engine.matching_strategy import (
    empty_last_rule_wins_overwrite_events_df,
)
from whep_digitize.postpro.rule_engine.schema_validation import build_conditional_rule_dictionary
from whep_digitize.postpro.utilities.stage_definitions import validate_postpro_stage_name
from whep_digitize.setup.helpers.assertions import require

_COLUMN_SOURCE = "column_source"


@dataclass(frozen=True, slots=True)
class PreparedRulePayload:
    """A rule file's execution plan.

    Attributes:
        grouped_dictionary: The standard rules grouped by ``(column_source, column_target)`` in
            deterministic application order.
        group_source_columns: The source column of each group (aligned with ``grouped_dictionary``).
        stage_name: The validated execution stage.
    """

    grouped_dictionary: tuple[pl.DataFrame, ...]
    group_source_columns: tuple[str, ...]
    stage_name: str


@dataclass(frozen=True, slots=True)
class RulePayloadResult:
    """Result of applying one rule payload.

    Attributes:
        data: The updated dataset.
        audit: The combined per-rule audit (empty frame when nothing applied).
        overwrite_events: The combined last-rule-wins overwrite diagnostics.
        changed_value_count: Total cells changed across every conditional group.
        changed_columns: Columns changed, in first-appearance (group) order.
    """

    data: pl.DataFrame
    audit: pl.DataFrame
    overwrite_events: pl.DataFrame
    changed_value_count: int
    changed_columns: tuple[str, ...]


def prepare_rule_payload_execution_plan(
    canonical_rules: pl.DataFrame, stage_name: str
) -> PreparedRulePayload:
    """Group a rule file's rules by (source, target) column in deterministic order.

    Args:
        canonical_rules: The canonical rule table.
        stage_name: The execution stage (validated).

    Returns:
        The :class:`PreparedRulePayload` execution plan.
    """
    stage = validate_postpro_stage_name(stage_name)
    grouped_dictionary = (
        tuple(build_conditional_rule_dictionary(canonical_rules, stage))
        if canonical_rules.height > 0
        else ()
    )
    group_source_columns = tuple(
        group.get_column(_COLUMN_SOURCE).item(0) for group in grouped_dictionary
    )
    return PreparedRulePayload(grouped_dictionary, group_source_columns, stage)


def apply_rule_payload(
    dataset: pl.DataFrame,
    canonical_rules: pl.DataFrame,
    stage_name: str,
    dataset_name: str,
    rule_file_id: str,
    execution_timestamp_utc: str,
    *,
    apply_match_normalization: bool = True,
    prepared_payload: PreparedRulePayload | None = None,
    trigger_columns: Sequence[str] | None = None,
) -> RulePayloadResult:
    """Apply one rule file's payload: each conditional group in order.

    Args:
        dataset: The dataset to transform.
        canonical_rules: The rule file's canonical rules.
        stage_name: The execution stage (validated).
        dataset_name: Dataset identifier (for audit / events).
        rule_file_id: Rule file identifier (for audit / events).
        execution_timestamp_utc: Execution timestamp string (audit metadata).
        apply_match_normalization: Whether match keys are normalized this application.
        prepared_payload: A pre-built execution plan (rebuilt from ``canonical_rules`` if ``None``).
        trigger_columns: When given, only apply conditional groups whose source column is listed.

    Returns:
        A :class:`RulePayloadResult` with the updated frame and accumulated diagnostics.
    """
    require(len(dataset_name) >= 1, "dataset_name must be a non-empty string")
    require(len(rule_file_id) >= 1, "rule_file_id must be a non-empty string")
    require(len(execution_timestamp_utc) >= 1, "execution_timestamp_utc must be a non-empty string")
    stage = validate_postpro_stage_name(stage_name)

    if canonical_rules.height == 0:
        return RulePayloadResult(
            data=dataset,
            audit=pl.DataFrame(),
            overwrite_events=empty_last_rule_wins_overwrite_events_df(),
            changed_value_count=0,
            changed_columns=(),
        )

    plan = prepared_payload or prepare_rule_payload_execution_plan(canonical_rules, stage)
    trigger = set(trigger_columns) if trigger_columns is not None else None

    current = dataset
    audit_frames: list[pl.DataFrame] = []
    overwrite_frames: list[pl.DataFrame] = []
    changed_value_count = 0
    changed_columns: list[str] = []

    for group, source_column in zip(
        plan.grouped_dictionary, plan.group_source_columns, strict=True
    ):
        if trigger is not None and source_column not in trigger:
            continue
        group_result = apply_conditional_rule_group(
            current,
            group_rules=group,
            stage_name=stage,
            dataset_name=dataset_name,
            rule_file_id=rule_file_id,
            execution_timestamp_utc=execution_timestamp_utc,
            apply_match_normalization=apply_match_normalization,
        )
        current = group_result.data
        audit_frames.append(group_result.audit)
        changed_value_count += group_result.changed_value_count
        changed_columns = _union_ordered(changed_columns, group_result.changed_columns)
        if group_result.overwrite_events.height > 0:
            overwrite_frames.append(group_result.overwrite_events)

    combined_audit = _combine_frames(audit_frames)
    combined_overwrite = (
        pl.concat(overwrite_frames, how="diagonal")
        if overwrite_frames
        else empty_last_rule_wins_overwrite_events_df()
    )
    return RulePayloadResult(
        data=current,
        audit=combined_audit,
        overwrite_events=combined_overwrite,
        changed_value_count=changed_value_count,
        changed_columns=tuple(changed_columns),
    )


def _union_ordered(existing: list[str], incoming: Sequence[str]) -> list[str]:
    """Return ``existing`` + new ``incoming`` values in first-appearance order."""
    return list(dict.fromkeys([*existing, *incoming]))


def _combine_frames(frames: Sequence[pl.DataFrame]) -> pl.DataFrame:
    """Row-bind schema-bearing frames; empty frame if none."""
    schema_bearing = [frame for frame in frames if frame.width > 0]
    if not schema_bearing:
        return pl.DataFrame()
    return pl.concat(schema_bearing, how="diagonal")
