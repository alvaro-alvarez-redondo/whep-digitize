---
name: migration
description: Port one R module to Python/polars with verified output parity.
---

# Migration

The core recurring task: migrate an R module from `whep-digitalization` to a Python module
in `whep-digitize`, preserving behavior **byte-for-byte** where outputs are compared — except
where a documented policy deliberately diverges (see *Parity discipline* below).

## Principles

- **Contract-first.** The stage's result type (`contracts.py`) is fixed. Implement to it;
  never widen a contract without updating consumers and tests.
- **Parity over cleverness.** Reproduce R semantics exactly, including documented quirks
  (see [r-to-python-mapping.md](../docs/r-to-python-mapping.md) §"quirks to preserve").
  Do not "fix" quirks unless the migration explicitly intends to.
- **Bottom-up.** Migrate leaf helpers before the functions that call them. Follow the
  dependency order in [codebase-map.md](../docs/codebase-map.md) and the roadmap.
- **Functional polars.** No by-reference mutation. Every R `set`/`:=` scatter becomes a
  new frame (join-back + `when/then`, or column rebuild).
- **Deterministic.** `sort_pipeline_stage_df` for ordering; code-point sorts; seed
  randomness. Identical inputs ⇒ identical outputs.

## Procedure

1. **Read the R source** and its codebase-map entry (R file + risk level).
2. **Read [r-to-python-mapping.md](../docs/r-to-python-mapping.md)** — the idiom table and
   the ranked parity risks. Identify which risks this module touches.
3. **Capture golden output** from R for representative fixtures (use the `parity-check`
   skill): run the R function on inputs, save outputs (TSV/parquet) under
   `tests/golden/<module>/`.
4. **Implement** the Python module against its contract. Prefer polars expressions over
   Python loops. Keep functions small and typed; Google-style docstrings.
5. **Test:** happy path, edge cases (empty, all-null, unicode/accented, duplicates), error
   cases, and a `@pytest.mark.parity` test asserting equality with the golden output.
6. **Gates:** `ruff check`, `ruff format`, `mypy`, `pytest` all green. Never lower pass rate.
7. **Update** the codebase-map entry to **[done]** and `.claude/progress.md`.

## Parity discipline

- Compare with `polars.testing.assert_frame_equal` (set `check_dtypes` deliberately — R is
  string-typed pre-audit).
- For error/diagnostic strings, compare exact text and order when a consumer depends on it.
- Normalization follows the documented POLICY (NFD diacritic strip + non-alphanumeric collapse),
  not R's ICU `Latin-ASCII`. Do NOT add character-specific overrides to match ICU's symbol /
  ligature / compatibility expansions — pin the intended behavior with a policy test instead.

## Constraints

- No feature expansion. No contract breaks unless the migration requires it (then update
  tests + docs). Deterministic only. Delete scratch files immediately (temp-file policy in
  [conventions.md](../docs/conventions.md)).
