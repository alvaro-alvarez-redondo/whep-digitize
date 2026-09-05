# Progress

Durable session state for the `/autocode` loop. Notes only — no scratch, no history dumps.

Append a short dated entry per completed iteration: what changed, which metric moved, and
anything a later session must not re-derive. Per-iteration metric rows live in
[results.tsv](results.tsv).

## Baseline metrics

| metric | value |
|--------|-------|
| tests | 813 passed / 0 failed |
| parity | 185 passed / 0 failed |
| ruff | 0 issues (whep_digitize pkg + tests) |
| mypy | 0 errors (strict, whep_digitize pkg) |
| perf (real data) | 93s full pipeline — 794,799 postpro rows, 17 rule groups, 3 passes |
| perf (fixtures-corpus) | ~1.05s, 3 iterations, best of 3 |

**Do not optimize against `fixtures-corpus`.** It is dominated by imports and file IO
(`_io.open_code` ~0.79s, `nt.stat` ~0.52s), the rule engine is ~6% of it, and run-to-run
variance is ±25%. Rule-engine work is invisible there. Benchmark against the real tree with
`WHEP_BENCH_INPUT_DIR=<repo>/data/input`, or profile one rule group directly.

## Log

- **2026-08-29**: Verified symmetric target tokenization (D1-D10) is implemented. Fixed benchmark `data/import` → `data/input` path bug.
- **2026-09-05**: Correctness — fixed the `empty_overwrite_events_df` import break (9 test modules could not collect); NULL source conditions never matching (D10); target `#EXACT#` ignoring surrounding whitespace; and a stale `target_pre` snapshot that silently discarded the source rewrite whenever a group named the same column on both sides (5 of the 17 real groups do). Documented the full-cell-over-token precedence as D11.
- **2026-09-05**: Performance — real pipeline 478s → 93s. Four changes, all verified byte-identical on the real dataset: batch the token-key encoding in `match_rule_target_condition_values` (it round-tripped through polars once per distinct cell value); evaluate `match_target_condition_token_map` on distinct `(target, condition)` pairs only (9.16M rows collapsed to 38k, 240x redundancy); suppress `#ANY#` / full-cell sentinel candidates no rule in the group can key against (2/3 of candidate rows); vectorize `_explode_source_candidates` and shift `row_id` in-expression.
- **2026-09-05**: Cleanup — removed 7 dead symbols and the never-passed `prepared_payload` parameter; deduplicated the audit-findings schema. Dead-symbol scan now reports zero.

## Known open items

- `prepared_group` / `PreparedConditionalGroup` / `prepare_conditional_rule_group` are exercised
  by tests but never used in production — the sibling `prepared_payload` path was removed as
  fully dead. Decide whether this two-phase API is wanted before building on it.
- `_explode_source_candidates` is still ~42% of the run; most of what remains is
  `per_row_tokens = ...to_list()`, which materializes 794,799 Python lists on every call while
  its only consumer indexes it for matched rows alone.
- The multi-pass loop rescans every row on passes 2 and 3 — a 3x multiplier on the whole
  rule engine. Narrowing it is a semantic change, not an optimization.
