"""Stage 2 — post-processing. The largest stage.

Runs the 9-step orchestration: audit -> init -> templates -> preflight ->
**clean -> standardize units -> harmonize** -> diagnostics -> persist. Public entry
point: :func:`whep_digitize.postpro.runner.run_postpro_pipeline` -> :class:`PostproResult`.

Sub-packages:

* :mod:`~whep_digitize.postpro.audit` — raw-data validation + numeric parse (stage entry)
* :mod:`~whep_digitize.postpro.utilities` — rule loading, templates, payload cache
* :mod:`~whep_digitize.postpro.clean_harmonize` — the multi-pass convergence driver
* :mod:`~whep_digitize.postpro.rule_engine` — rule matching + application (the heart)
* :mod:`~whep_digitize.postpro.standardize_units` — unit conversion + aggregation
* :mod:`~whep_digitize.postpro.diagnostics` — preflight, summaries, audit workbooks
"""

from __future__ import annotations
