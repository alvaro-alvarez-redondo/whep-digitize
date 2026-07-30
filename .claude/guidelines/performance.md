---
name: performance
description: Identify and optimize performance-critical Python/polars code.
---

# Performance

Profile first — optimize the measured hot path, not a guess (`cProfile`, `py-spy`, or
`polars` query plans via `.explain()`). Prefer:

- **polars-native, vectorized expressions** over Python loops / `map_elements`. Reach for
  `map_elements` only for genuinely scalar-Python work (e.g. the normalization unique-value
  fast path), and apply it to `unique()` values then join back.
- **Lazy frames** (`pl.LazyFrame` / `.lazy().collect()`) so polars can fuse and parallelize.
- **Fewer materializations**: chain expressions; avoid intermediate `.to_pandas()`/`.to_list()`.
- **Right join strategy**: keyed joins over row-wise Python; `group_by(...).agg(...)` over
  manual accumulation.

Measure before/after on a frozen input (the live dataset grows — freeze fixtures for A/Bs).
Look for >5% wins; ignore noise. Preserve correctness: tests (incl. parity) pass before and
after.

The committed benchmark ground truth will live under `.claude/bench/` (read-only once added).
Ad-hoc profiling harnesses and their output are **temporary — delete immediately** (temp-file
policy in [conventions.md](../docs/conventions.md)). Fold durable findings into
`.claude/progress.md`.
