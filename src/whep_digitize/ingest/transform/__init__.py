r"""Ingest / transform — ports ``r/1-import_pipeline/12-transform/`` (algorithmic core).

* :mod:`~whep_digitize.ingest.transform.transform_utils` (``12-transform-utils.R``) —
  ``identify_year_columns`` (name matches ``^\d{4}(-\d{4})?$`` and is not a metadata
  column), key-field normalization, year-header cleanup + duplicate-collision guard.
* :mod:`~whep_digitize.ingest.transform.reshape` (``12-reshape.R``) — the wide->long melt
  (``data.table::melt`` -> ``pl.DataFrame.unpivot``, recomputing year columns explicitly),
  ``document`` / ``notes`` / ``yearbook`` enrichment, and the per-file ``transform_file_df``.
* :mod:`~whep_digitize.ingest.transform.processing` (``12-processing.R``) — the fused
  read+transform-per-batch path (``read_transform_pipeline_files``, ``transform_single_file``)
  and its ``ProcessPoolExecutor`` parallelism, with deterministic output order independent of
  worker count and a graceful sequential fallback.
"""

from __future__ import annotations
