"""Postpro / diagnostics — ports ``r/2-postpro_pipeline/25-postpro_diagnostics/``.

Preflight checks, cross-stage rule summaries (matched + unmatched), and the persisted logs
TSVs.

Status (risk):

* ``preflight.py`` — ``collect_postpro_preflight`` /
  ``assert_postpro_preflight`` (rule dirs, naming patterns, expected columns).
* ``rule_summaries.py`` — clean/harmonize matched-rule
  summary + rule catalog + unmatched summary (null-safe anti-join).
* ``standardize_summaries.py`` — standardize catalog +
  matched/unmatched summaries (normalized-key counts branch).
* ``persist.py`` — ``build_postpro_diagnostics`` and ``persist_postpro_logs``, which writes
  one tab-separated logs file per stage.
"""

from __future__ import annotations
