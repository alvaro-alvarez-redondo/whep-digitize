# Conventions & gotchas

## Running the pipeline

```python
from whep_digitize.pipeline import run_pipeline
run_pipeline(show_view=False)          # setup -> ingest -> postpro -> export
```

```bash
whep-digitize run          # full pipeline (CLI)
whep-digitize bootstrap    # Stage 0 only: build config + create dirs
```

Unlike the R pipeline, **importing a module never runs anything** — stages are explicit
calls. All four stages (setup → ingest → postpro → export) are implemented and wired, so
`run` executes the full pipeline end-to-end.

## Environment (this Windows host)

- Python is invoked via the launcher: **`py -3.14`** (Python 3.14.5). `python` on PATH is
  the Microsoft Store stub — do not use it. (Same "not on PATH" pattern as R here.)
- The dev environment lives in `.venv/` (created with `py -3.14 -m venv .venv`).
- **`uv` is not installed** on this host. The canonical workflow is `uv sync --extra dev`
  / `uv run …`; the pip fallback is `.venv/Scripts/python.exe -m pip install -e ".[dev]"`.
- All tools are run through the venv Python:
  `.venv/Scripts/python.exe -m {pytest|ruff|mypy}`.

## Running tests / quality gates

```bash
.venv/Scripts/python.exe -m pytest -q            # tests (ground truth; mirrors testthat)
.venv/Scripts/python.exe -m ruff check .          # lint
.venv/Scripts/python.exe -m ruff format .         # format
.venv/Scripts/python.exe -m mypy                  # strict type check
```

`pytest` uses `pythonpath = ["src"]`, so tests import `whep_digitize` without an install.
`tests/conftest.py` provides `project_dir` / `config` / `sample_long_df` fixtures.

## Loading / import order

- A real package — explicit imports, no `source()` and no numeric-prefix load order.
- No import-time side effects: modules only define; running happens in `run_*` functions.
- `setup` is the shared foundation every stage imports (`constants`, `Config`, helpers).

## Determinism

- Identical inputs + options ⇒ identical outputs.
- String-typed through import; `value` → `Float64` only at the postpro audit step.
- Every sort goes through `sort_pipeline_stage_df` (`nulls_last=True, maintain_order=True`);
  polars sorts by Unicode code point (locale-independent) — matches R radix for ASCII keys.
- Seed any randomness; tests use temp dirs + in-memory fixtures, no network/FS side effects.
- **Normalization** follows the documented POLICY (NFD diacritic strip + non-alphanumeric
  collapse), deliberately NOT R's ICU `Latin-ASCII` — see
  [r-to-python-mapping.md](r-to-python-mapping.md). Deterministic via stdlib `unicodedata`;
  pin behavior with policy tests, not R goldens.

## Parallelism (planned, Phase 5)

Two sites parallelize in R: the fused import read+transform and list export. In Python use
`concurrent.futures.ProcessPoolExecutor`. Preserve the invariant: **deterministic output
order independent of worker count**, and parallel-only-when->1-batch with a graceful
sequential fallback. Default is sequential.

## Contracts & typing

- Stages return typed frozen dataclasses (`contracts.py`); never assign into globals or hang
  data on frame attributes (polars has none).
- `mypy` runs in **strict** mode over `src` and `tests`. Public functions are fully typed
  with Google-style docstrings (the roxygen2 analogue; enforced by ruff `D`).

## Temporary & scratch files

**Delete every temporary file as soon as it is no longer needed** — never defer to commit
time, never commit one. This covers run logs (`*.out`, gitignored), one-off scripts,
profiling/benchmark harnesses, and generated diagnostics. Prefer `tempfile` dirs the OS
reclaims. Durable records go in `.claude/progress.md` / `.claude/results.tsv`.

## Nextcloud

The repo sits under a synced Nextcloud folder; reconciles can silently revert uncommitted
working-tree changes. **Commit promptly** to protect work.

## Maintaining these docs

- Reference module/function names, not line numbers.
- Update the matching doc when changing a contract, entry point, constant, or option.
- Each doc has a distinct job — don't duplicate across them.
