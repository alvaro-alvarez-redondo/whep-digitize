"""Postpro / utilities — shared support modules for the post-processing stage.

Modules:

* ``stage_definitions.py`` — canonical rule columns + stage names (centralized in
  :mod:`whep_digitize.setup.constants`).
* ``output_roots.py`` — resolve/create the audit subtree
  (:class:`~whep_digitize.postpro.utilities.output_roots.PostproOutputPaths`).
* ``diagnostics.py`` — ``build_layer_diagnostics`` ->
  :class:`~whep_digitize.contracts.LayerDiagnostics`.
* ``templates.py`` — rule-template workbooks; ``read_rule_table`` reads clean/harmonize rule
  files all-as-text with a sheet schema-matching heuristic; ``load_stage_rule_payloads``
  discovery.
* ``payload_cache.py`` — 2-level (memory+disk) rule-payload cache keyed by md5 of sorted rule
  files. Disabled by default; the disk layer is pickle-backed because parquet cannot hold the
  nested bundle.
"""

from __future__ import annotations
