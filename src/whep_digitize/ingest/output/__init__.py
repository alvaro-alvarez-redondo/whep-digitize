"""Ingest / output — ports ``r/1-import_pipeline/13-output/``.

* :mod:`~whep_digitize.ingest.output.validate` (``13-validate.R``) — the vectorized,
  document-major validator ``validate_long_df_by_document`` (mandatory-field, year-range,
  duplicate checks) with per-document row ids, first-appearance ordering, a 4-key stable
  sort, and verbatim error-string formats.
* :mod:`~whep_digitize.ingest.output.consolidate` (``13-output.R``) —
  ``consolidate_audited_df`` (``pl.concat(how="diagonal")`` + canonical column reordering)
  and ``validate_output_column_order``.
"""

from __future__ import annotations
