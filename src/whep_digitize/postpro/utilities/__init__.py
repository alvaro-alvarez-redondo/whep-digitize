"""Postpro / utilities — ports ``r/2-postpro_pipeline/21-postpro_utilities/``.

Status (risk):

* ``stage_definitions.py`` <- ``21-stage-definitions.R`` — **[done]** canonical rule columns +
  stage names (centralized in :mod:`whep_digitize.setup.constants`). (LOW)
* ``output_roots.py`` <- ``21-output-roots.R`` — **[done]** resolve/create the audit subtree
  (:class:`~whep_digitize.postpro.utilities.output_roots.PostproOutputPaths`). (LOW)
* ``diagnostics.py`` <- ``21-diagnostics.R`` — **[done]** ``build_layer_diagnostics`` base object
  -> :class:`~whep_digitize.contracts.LayerDiagnostics`. (LOW)
* ``templates.py`` <- ``21-template-rules.R`` — **[done]** rule-template workbooks;
  ``read_rule_table`` reads clean/harmonize rule files all-as-text with a sheet schema-matching
  heuristic; ``load_stage_rule_payloads`` discovery. (MEDIUM)
* ``payload_cache.py`` <- ``21-runtime-cache.R`` — **[done]** 2-level (memory+disk) rule-payload
  cache keyed by md5 of sorted rule files. Disabled by default; disk layer is pickle-backed
  (the ``saveRDS`` analogue; parquet cannot hold the nested bundle). (MEDIUM; low priority)
"""

from __future__ import annotations
