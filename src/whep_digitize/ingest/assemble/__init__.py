"""Ingest / output — validation and consolidation.

* :mod:`~whep_digitize.ingest.assemble.validate` — the vectorized, file-major validator
  ``validate_long_df_by_file`` (mandatory-field, year-range, duplicate checks) with
  per-file row ids, first-appearance ordering, a 4-key stable sort, and verbatim
  error-string formats.
* :mod:`~whep_digitize.ingest.assemble.consolidate` — ``consolidate_audited_df``
  (``pl.concat(how="diagonal")`` + canonical column reordering) and
  ``validate_column_order``.
"""

from __future__ import annotations
