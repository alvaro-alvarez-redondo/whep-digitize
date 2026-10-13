"""Unit tests for the multi-pass clean/harmonize driver and its parts.

Covers :mod:`whep_digitize.postpro.clean_harmonize` +
:mod:`whep_digitize.postpro.rule_engine.payload_application`. End-to-end convergence against the
frozen reference lives in ``tests/parity/test_layer_batch_parity.py``; these pin the behavioral
contract directly — the pass-1-only normalization, converge-at-zero-change, and cycle detection.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest
from openpyxl import Workbook

from whep_digitize.postpro.clean_harmonize.controls_cache import (
    build_stage_state_record,
    find_repeated_stage_state_pass,
    resolve_stage_multi_pass_controls,
)
from whep_digitize.postpro.clean_harmonize.layer_runner import (
    run_cleaning_layer_batch,
    run_harmonize_layer_batch,
)
from whep_digitize.postpro.clean_harmonize.stage_frames import (
    canonicalize_post_loop_annotation_columns,
    drop_empty_footnotes_column,
)
from whep_digitize.postpro.rule_engine.payload_application import (
    apply_rule_payload,
    prepare_rule_payload_execution_plan,
)
from whep_digitize.postpro.utilities.payload_cache import clear_stage_payload_memory_cache
from whep_digitize.setup.config import Config
from whep_digitize.setup.helpers.strings import canonicalize_token_column

_CANONICAL = (
    "column_source",
    "value_source_raw",
    "value_source",
    "column_target",
    "value_target_raw",
    "value_target",
)
_TIMESTAMP = "2026-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    clear_stage_payload_memory_cache()
    yield
    clear_stage_payload_memory_cache()


def _series(values: list[str | None]) -> pl.Series:
    return pl.Series(values, dtype=pl.String)


def _canonical_rule(
    column_source: str,
    value_source_raw: str,
    column_target: str,
    value_target_raw: str | None,
    value_target: str,
    *,
    value_source: str | None = None,
    source_value_column_present: bool = False,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "column_source": _series([column_source]),
            "value_source_raw": _series([value_source_raw]),
            "value_source": _series([value_source]),
            "column_target": _series([column_target]),
            "value_target_raw": _series([value_target_raw]),
            "value_target": _series([value_target]),
            "source_value_column_present": pl.Series(
                [source_value_column_present], dtype=pl.Boolean
            ),
        }
    )


def _write_rule_file(
    path: Path, prefix: str, rows: list[tuple[str, str, str, str | None, str]]
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"{prefix}_rules"
    sheet.append(
        [
            f"{prefix}_column_source",
            f"{prefix}_value_source_raw",
            f"{prefix}_column_target",
            f"{prefix}_value_target_raw",
            f"{prefix}_value_target",
        ]
    )
    for row in rows:
        sheet.append(list(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


# --------------------------------------------------------------------------- stage_frames


def test_canonicalize_dedupes_sorts_and_blanks() -> None:
    result = canonicalize_token_column(_series(["b; a; a", "solo", None, "   ", "c;;b"]))
    assert result.to_list() == ["a; b", "solo", None, None, "b; c"]


def test_canonicalize_post_loop_touches_only_annotation_columns() -> None:
    frame = pl.DataFrame({"notes": _series(["z; a"]), "unit": _series(["b; a"])})
    result = canonicalize_post_loop_annotation_columns(frame)
    assert result.get_column("notes").to_list() == ["a; z"]
    assert result.get_column("unit").to_list() == ["b; a"]  # not an annotation column


def test_drop_empty_footnotes_variants() -> None:
    all_null = pl.DataFrame({"footnotes": _series([None, None]), "unit": _series(["t", "kg"])})
    assert drop_empty_footnotes_column(all_null).columns == ["unit"]

    has_value = pl.DataFrame({"footnotes": _series([None, "fao"])})
    assert drop_empty_footnotes_column(has_value).columns == ["footnotes"]

    absent = pl.DataFrame({"unit": _series(["t"])})
    assert drop_empty_footnotes_column(absent).columns == ["unit"]


# --------------------------------------------------------------------------- controls_cache


def test_resolve_multi_pass_controls_defaults() -> None:
    controls = resolve_stage_multi_pass_controls(object(), "clean")
    assert controls.enabled is True
    assert controls.max_passes == 10
    assert controls.cycle_policy == "warn"
    assert controls.diagnostics_verbosity == "compact"


def test_state_record_detects_repeat_and_screens_by_fingerprint() -> None:
    frame = pl.DataFrame({"unit": _series(["a", "b"])})
    same = pl.DataFrame({"unit": _series(["a", "b"])})
    different_values = pl.DataFrame({"unit": _series(["a", "c"])})
    different_shape = pl.DataFrame({"unit": _series(["a"])})

    records = [build_stage_state_record(frame)]
    indexes = [0]
    assert find_repeated_stage_state_pass(records, indexes, build_stage_state_record(same)) == 0
    assert (
        find_repeated_stage_state_pass(records, indexes, build_stage_state_record(different_values))
        is None
    )
    assert (
        find_repeated_stage_state_pass(records, indexes, build_stage_state_record(different_shape))
        is None
    )


# --------------------------------------------------------------------------- payload_application


def test_prepare_plan_groups_every_rule_including_footnotes() -> None:
    # There is no separate footnote path any more: a footnote rule is just a rule whose source
    # column is ``footnotes``, grouped like any other.
    rules = pl.concat(
        [
            _canonical_rule("footnotes", "fao", "footnotes", "fao", "faostat"),
            _canonical_rule("commodity", "wheat", "unit", "t", "tonne"),
        ]
    )
    plan = prepare_rule_payload_execution_plan(rules, "clean")
    assert len(plan.grouped_dictionary) == 2
    # Group order is by (column_target, column_source): footnotes -> footnotes, then unit.
    assert plan.group_source_columns == ("footnotes", "commodity")


def test_apply_rule_payload_empty_rules_is_noop() -> None:
    dataset = pl.DataFrame({"commodity": _series(["wheat"]), "unit": _series(["t"])})
    empty = pl.DataFrame(schema=dict.fromkeys(_CANONICAL, pl.String))
    result = apply_rule_payload(dataset, empty, "clean", "whep", "rules.xlsx", _TIMESTAMP)
    assert result.changed_value_count == 0
    assert result.changed_columns == ()
    assert result.data.get_column("unit").to_list() == ["t"]


def test_apply_rule_payload_applies_conditional_rule() -> None:
    dataset = pl.DataFrame({"commodity": _series(["wheat", "rice"]), "unit": _series(["t", "kg"])})
    rule = _canonical_rule("commodity", "wheat", "unit", "t", "tonne")
    result = apply_rule_payload(dataset, rule, "clean", "whep", "rules.xlsx", _TIMESTAMP)
    assert result.data.sort("commodity").get_column("unit").to_list() == ["kg", "tonne"]
    assert result.changed_value_count == 1
    assert result.changed_columns == ("unit",)
    assert result.audit.height == 1


def test_apply_rule_payload_trigger_columns_skips_nonlisted_group() -> None:
    dataset = pl.DataFrame({"commodity": _series(["wheat"]), "unit": _series(["t"])})
    rule = _canonical_rule("commodity", "wheat", "unit", "t", "tonne")
    result = apply_rule_payload(
        dataset, rule, "clean", "whep", "rules.xlsx", _TIMESTAMP, trigger_columns=["polity"]
    )
    assert result.changed_value_count == 0
    assert result.data.get_column("unit").to_list() == ["t"]


# --------------------------------------------------------------------------- layer_runner


def _clean_config(config: Config) -> Config:
    config.paths.data.input.cleaning.mkdir(parents=True, exist_ok=True)
    return config


def test_run_cleaning_converges_in_two_passes(config: Config) -> None:
    _write_rule_file(
        config.paths.data.input.cleaning / "clean_rules.xlsx",
        "clean",
        [("commodity", "wheat", "unit", "t", "tonne")],
    )
    dataset = pl.DataFrame(
        {
            "commodity": _series(["wheat", "rice"]),
            "unit": _series(["t", "kg"]),
            "value": _series(["1", "2"]),
        }
    )
    result = run_cleaning_layer_batch(dataset, config, execution_timestamp_utc=_TIMESTAMP)
    assert result.data.sort("commodity").get_column("unit").to_list() == ["kg", "tonne"]
    multi_pass = result.diagnostics.multi_pass
    assert multi_pass is not None
    assert multi_pass.passes_executed == 2
    assert multi_pass.converged is True
    assert multi_pass.stop_reason == "converged_zero_change"
    assert result.pass_diagnostics.get_column("changed_value_count").to_list() == [1, 0]


def test_run_no_rules_converges_single_pass(config: Config) -> None:
    _clean_config(config)  # empty clean import dir
    dataset = pl.DataFrame({"commodity": _series(["wheat"]), "unit": _series(["t"])})
    result = run_cleaning_layer_batch(dataset, config, execution_timestamp_utc=_TIMESTAMP)
    multi_pass = result.diagnostics.multi_pass
    assert multi_pass is not None
    assert multi_pass.passes_executed == 1
    assert multi_pass.converged is True
    assert result.diagnostics.matched_count == 0


def test_run_drops_all_null_footnotes_after_loop(config: Config) -> None:
    _clean_config(config)
    dataset = pl.DataFrame({"commodity": _series(["wheat"]), "footnotes": _series([None])})
    result = run_cleaning_layer_batch(dataset, config, execution_timestamp_utc=_TIMESTAMP)
    assert "footnotes" not in result.data.columns


def test_run_detects_cycle_and_warns(config: Config) -> None:
    # 2-rule oscillation: commodity=x, unit=a → unit=b and commodity=x, unit=b → unit=a.
    # Both rules share value_source_raw="x" but differ in value_target_raw.
    # They are in the same group (no decomposition).
    #
    # With first-write-wins: both rules are in the same group. Rule 1's target condition
    # is "a", Rule 2's target condition is "b". The dataset has unit="a", so only Rule 1's
    # target condition matches. Rule 2 doesn't match because unit="a" != "b".
    #
    # Result: unit "a" → "b" (Rule 1 applies), then Rule 2 doesn't match.
    # Pass 2: Rule 1's source condition still matches (commodity=x), but Rule 1's target
    # condition is "a" and unit is now "b" → no match. Rule 2's target condition is "b" and
    # unit is "b" → matches. So Rule 2 applies: unit "b" → "a".
    # Pass 3: Back to unit="a", same as Pass 0 → cycle detected.
    #
    # Actually, with first-write-wins in the same group: both rules match the same source
    # token (commodity=x). The target conditions differ (a vs b). The dataset has unit="a".
    # Only Rule 1's target condition matches. Rule 2 is filtered out by target condition.
    # So only Rule 1 applies: unit "a" → "b".
    # Pass 2: unit="b", Rule 1's target condition "a" doesn't match. Rule 2's target
    # condition "b" matches. Rule 2 applies: unit "b" → "a".
    # Pass 3: unit="a" again → cycle detected.
    #
    # Wait - but with first-write-wins, both rules are in the same group and compete for
    # the same source token. However, they have different target conditions, so the
    # collision is on the source side, not the target substitution side.
    # The first-write-wins applies to token_substitutions for the same token.
    # Rule 1 writes unit "a" → "b", Rule 2 writes unit "b" → "a".
    # These are different target conditions, so only one matches per pass.
    # The oscillation happens across passes, not within a pass.
    _write_rule_file(
        config.paths.data.input.cleaning / "clean_rules.xlsx",
        "clean",
        [("commodity", "x", "unit", "a", "b"), ("commodity", "x", "unit", "b", "a")],
    )
    dataset = pl.DataFrame({"commodity": _series(["x"]), "unit": _series(["a"])})
    result = run_cleaning_layer_batch(dataset, config, execution_timestamp_utc=_TIMESTAMP)
    multi_pass = result.diagnostics.multi_pass
    assert multi_pass is not None
    # With first-write-wins (no decomposition), both rules are in the same group.
    # Pass 1: unit="a", only Rule 1's target condition ("a") matches → unit="b".
    # Pass 2: unit="b", only Rule 2's target condition ("b") matches → unit="a".
    # Pass 2's state matches pass 0's state → cycle detected.
    assert multi_pass.cycle_detected is True
    assert multi_pass.stop_reason == "cycle_detected"
    assert multi_pass.passes_executed == 2
    # Unit is "a" (Rule 2 applied in pass 2, reverting to original).
    assert result.data.get_column("unit").to_list() == ["a"]


def test_run_harmonize_uses_harmonize_rules(config: Config) -> None:
    _write_rule_file(
        config.paths.data.input.harmonization / "harmonize_rules.xlsx",
        "harmonize",
        [("commodity", "rice", "unit", "kg", "kilogram")],
    )
    dataset = pl.DataFrame({"commodity": _series(["rice"]), "unit": _series(["kg"])})
    result = run_harmonize_layer_batch(dataset, config, execution_timestamp_utc=_TIMESTAMP)
    assert result.data.get_column("unit").to_list() == ["kilogram"]
