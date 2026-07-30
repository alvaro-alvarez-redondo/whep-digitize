"""Ingest / reading — ports ``r/1-import_pipeline/11-reading/``.

* :mod:`~whep_digitize.ingest.reading.read_utils` (``11-read-utils.R``) — the typed
  ``(data, errors)`` read-result plumbing (:class:`~.read_utils.ReadResult` /
  :class:`~.read_utils.SafeReadResult`) + safe-execution wrapper.
* :mod:`~whep_digitize.ingest.reading.header_normalization` (``11-header-normalization.R``)
  — the ordered multi-regex header chain + diacritic-strip/lowercase transliteration +
  canonical/alias renames (``country`` -> ``polity``) with collision guards.
* :mod:`~whep_digitize.ingest.reading.sheet_read` (``11-sheet-read.R``) — read each sheet
  all-as-text (``pl.read_excel(engine="calamine", infer_schema_length=0)``); tag
  ``variable`` := sheet name; keep rows where ANY base column is non-empty.
* :mod:`~whep_digitize.ingest.reading.batching` (``11-batching.R``) — workbook batching,
  worker resolution (``"auto"`` -> ``min(8, cpu-1)``), single-batch reader. The parallel
  orchestration over batches (R ``read_pipeline_files``) lands with the stage runner.
"""

from __future__ import annotations
