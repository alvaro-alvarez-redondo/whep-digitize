"""Postpro / rule_engine — the algorithmic heart of the post-processing stage.

Match dataset rows on ``column_source``/``value_source_raw`` (and an optional
``column_target``/``value_target_raw`` guard), then rewrite source and update target via a
strategy. Every write is a functional polars scatter (join-back on a row index + ``when/then``);
no frame is ever mutated in place.

Modules:

* ``matching_strategy.py`` — match-key encoding (missing -> ``na_match_key``), strategy config,
  tokenized target columns (``footnotes``, ``notes``).
* ``matching_values.py`` — tokenized ``;``-membership match, order-preserving concat merge,
  elementwise change count (drives multi-pass convergence).
* ``target_apply.py`` — ``last_rule_wins`` (stable-sort + group-last) with overwrite-event
  emission, and ``concatenate``.
* ``conditional_group.py`` — cartesian keyed join on ``source_key``, subset target-condition
  match, source+target scatter, audit.
* ``footnote_rules.py`` — explode ``;`` tokens -> match -> resolve (remove > replace > original)
  -> reconstruct. The most intricate module here.
* ``schema_validation.py`` — coerce/validate rules, duplicate/conflict checks, code-point-ordered
  conditional dictionary.
* ``payload_application.py`` — per-file orchestration: footnote rules first, then each
  conditional group.
"""

from __future__ import annotations
