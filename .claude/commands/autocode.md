# Autocode (whep-digitize)

Autonomous optimization loop for this Python project. Modify source, run the scoring
harness, keep improvements, discard regressions, repeat. Config: [`autocode.toml`](../../autocode.toml).
State: [progress.md](../progress.md), [results.tsv](../results.tsv).

## Project detection (already done)

- **Language:** Python 3.11+ (this host: `py -3.14`, venv at `.venv/`).
- **Tests:** `pytest` (`.venv/Scripts/python.exe -m pytest`).
- **Quality:** `ruff check` + `mypy` (strict).
- **Performance:** full-pipeline benchmark under `.claude/bench/` (added once stages exist).

## Metrics (see `autocode.toml`)

| Metric | Command | Direction | Weight |
|--------|---------|-----------|--------|
| tests | `pytest -q` (pass %) | up | 0.5 |
| quality | `ruff check` (issue count) | down | 0.2 |
| types | `mypy` (error count) | down | 0.2 |
| performance | `.claude/bench/bench.py` (seconds) | down | 0.1 (pending stages) |

**Critical rule:** never accept a change that drops test pass rate below baseline —
correctness is not tradeable. Parity tests (`@pytest.mark.parity`) are part of correctness.

## Modifiable vs read-only

- **CAN modify:** `src/**/*.py` (and `autocode.toml` only during setup).
- **CANNOT modify:** `tests/**`, `.claude/bench/**`, `tests/golden/**` — ground truth.
- Do **not** add dependencies without explicit approval (edit `pyproject.toml` deps only
  when asked).

## Loop

1. **Assess** `results.tsv` + source. Weakest metric? Best opportunity?
2. **Hypothesize** a single focused change.
3. **Edit** source.
4. **Commit** (`git add -A && git commit`).
5. **Score** — run each metric, redirect to a gitignored `*.out`, parse.
6. **Log** to `results.tsv` (`keep`/`discard`/`crash`).
7. **Keep** if composite improved AND tests ≥ baseline; else `git reset --hard HEAD~1`.

## Migration-aware note

For this project, the highest-value "optimization" is usually **advancing the migration**:
porting a scaffolded module (see [migration-roadmap.md](../docs/migration-roadmap.md)) with
passing parity tests raises coverage and moves the pipeline toward end-to-end. Prefer the
`migrate-module` skill for that; use the pure autocode loop for perf/quality once a stage is
functionally complete.

Delete every scratch/log file as soon as it is no longer needed. Durable findings →
`progress.md`. Never stop to ask mid-loop; when out of ideas, re-read with fresh eyes.
