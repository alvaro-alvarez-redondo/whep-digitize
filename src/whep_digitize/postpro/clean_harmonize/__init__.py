"""Postpro / clean_harmonize — the multi-pass convergence engine.

Shared by the clean and harmonize stages; the algorithmic core of the post-processing stage.

Modules:

* ``layer_runner.py`` — ``run_rule_stage_layer_batch`` (+ ``run_cleaning_layer_batch`` /
  ``run_harmonize_layer_batch``): iterate passes (max 10), applying all rule payloads each pass;
  stop on ``changed_value_count == 0`` (converged), repeated state (cycle -> warn/abort), or max
  passes. Match normalization runs on pass 1 only. Returns a typed
  :class:`~whep_digitize.postpro.clean_harmonize.layer_runner.StageLayerResult`.
* ``controls_cache.py`` — multi-pass control resolution and cycle detection. State fingerprinting
  uses a deterministic content hash (``df.hash_rows()`` folded), screened by a cheap
  metadata-only fingerprint so most passes never compute the full hash.
* ``stage_frames.py`` — semicolon-token canonicalization of ``notes``/``footnotes`` (dedupe +
  code-point sort), and dropping an all-missing footnotes column.
"""

from __future__ import annotations
