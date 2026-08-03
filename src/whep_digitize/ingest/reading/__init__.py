"""Ingest / reading — workbook reading, header normalization, batching.

* :mod:`~whep_digitize.ingest.reading.read_utils` — the typed ``(data, errors)`` read-result
  plumbing (:class:`~.read_utils.ReadResult` / :class:`~.read_utils.SafeReadResult`) +
  safe-execution wrapper.
* :mod:`~whep_digitize.ingest.reading.header_normalization` — the ordered multi-regex header
  chain + diacritic-strip/lowercase transliteration + canonical/alias renames
  (``country`` -> ``polity``) with collision guards.
* :mod:`~whep_digitize.ingest.reading.sheet_read` — read each sheet all-as-text
  (``pl.read_excel(engine="calamine", infer_schema_length=0)``); tag ``variable`` := sheet
  name; keep rows where ANY base column is non-empty.
* :mod:`~whep_digitize.ingest.reading.batching` — workbook batching, worker resolution
  (``"auto"`` -> ``min(8, cpu-1)``), single-batch reader. The parallel orchestration over
  batches lives in :mod:`whep_digitize.ingest.transform.processing`.
"""

from __future__ import annotations
