# Progress

Durable session state for the `/autocode` loop. Notes only — no scratch, no history dumps.

Append a short dated entry per completed iteration: what changed, which metric moved, and
anything a later session must not re-derive. Per-iteration metric rows live in
[results.tsv](results.tsv).

## Baseline metrics

| metric | value |
|--------|-------|
| tests | 720 passed / 0 failed |
| ruff | 0 issues |
| mypy | 0 errors (strict) |
| perf | see `results.tsv` (`.claude/bench/bench.py`) |

## Log

*No autocode iterations recorded yet.*
