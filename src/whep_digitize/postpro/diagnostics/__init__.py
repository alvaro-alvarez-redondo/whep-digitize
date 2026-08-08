"""Postpro / diagnostics — ports ``r/2-postpro_pipeline/25-postpro_diagnostics/``.

Preflight checks, cross-stage rule summaries (matched + unmatched), and the persisted audit /
overwrite-subset workbooks.

Status (risk):

* ``preflight.py`` — ``collect_postpro_preflight`` /
  ``assert_postpro_preflight`` (rule dirs, naming patterns, expected columns).
* ``rule_summaries.py`` — clean/harmonize matched-rule
  summary + rule catalog + unmatched summary (null-safe anti-join).
* ``standardize_summaries.py`` — standardize catalog +
  matched/unmatched summaries (normalized-key counts branch).
* ``output.py`` — ``build_postpro_diagnostics``,
  last-rule-wins overwrite subset (group-by row + join), ``persist_postpro_audit`` (multi-sheet
  xlsx).
"""

from __future__ import annotations
