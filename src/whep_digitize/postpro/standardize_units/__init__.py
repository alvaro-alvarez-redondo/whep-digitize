"""Postpro / standardize_units — ports ``r/2-postpro_pipeline/24-standardize_units/``.

Affine unit conversion (``value * factor + offset``) by commodity/unit, with a leading
numeric multiplier folded into the value (e.g. ``"1000 head"``, value 5 -> value 5000,
unit ``"head"``), a two-stage (specific -> ``"#ALL#"`` fallback) match, and
optional duplicate-group aggregation.

Status (risk):

* ``engine.py`` — ``apply_standardize_rules``: prefix
  fold, revert probe, two-stage join, affine convert; contract
  ``(data, matched_count, unmatched_count, matched_rule_counts)`` via ``StandardizeResult``.
* ``rules_setup.py`` — header aliasing, schema + conversion
  validation (normalized-key dedupe, chained-rule guard), ``prepare_standardize_rules``. The
  xlsx multi-sheet rule readers live at the orchestration IO boundary.
* ``aggregation.py`` — sum the measure over duplicate groups (an all-null group yields null),
  order/schema preserving, idempotent.
* ``orchestration.py`` — `run_standardize_units_layer_batch` → `StandardizeLayerResult`, the xlsx
  rule readers, `build_standardize_layer_audit`, diagnostics.
"""

from __future__ import annotations
