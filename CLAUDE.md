# CLAUDE.md

whep-digitize — Python/Polars port of the WHEP digitization pipeline (the R project
`whep-digitalization`). A deterministic four-stage pipeline processing WHEP source
workbooks: setup (0) → ingest (1) → postpro (2) → export (3).

**This is a migration project.** The R repo (sibling `whep-digitalization/`) is the source
of truth; the goal is byte-for-byte output parity **except for the intentional
normalization-policy divergence** (13 rows on the full **1,339-workbook** dataset; value sums and
row counts unchanged — see [r-to-python-mapping.md](.claude/docs/r-to-python-mapping.md) risk #1).
Automated CI parity covers only the **6-workbook fixture corpus**; the full dataset is checked by
`scripts/parity_full_dataset.py`, which needs R — see
[full-dataset-parity.md](.claude/docs/full-dataset-parity.md).
Stage 0 is implemented; stages 1–3 are
scaffolded with typed contracts. See [migration-roadmap.md](.claude/docs/migration-roadmap.md).

## How to work

- **Act autonomously.** Decide when context is sufficient; default to action. Ask only when
  a decision is ambiguous, irreversible, high-impact, or under-specified. Document assumptions.
- **Migrate with the skills.** Use `migrate-module` to port an R module, `parity-check` to
  verify against R golden output, `migration-status` to see what's next. Parallel agents on
  independent modules when it helps (the roadmap marks concurrent tracks).
- **Use `/autocode`** for perf/quality/test work once a stage is functionally complete.
- **Reuse project context.** Read `.claude/docs/` (kept current) instead of rescanning.
  Start with [r-to-python-mapping.md](.claude/docs/r-to-python-mapping.md) and
  [codebase-map.md](.claude/docs/codebase-map.md).
- **Deliver complete solutions.** Don't stop at partial ports; a module is done only with
  passing parity + gates.
- **One concern per change.** Focused diffs. Delete every temporary file the moment it is no
  longer needed — never defer to commit time, never commit one (temp-file policy in
  [conventions.md](.claude/docs/conventions.md)).
- **Tests are ground truth.** Every behavior change ships with tests (incl. parity). Never
  lower pass rate.
- **Log deferred bugs (mandatory).** Whenever you identify a bug but intentionally do **not**
  fix it in the same session, you MUST add an entry to the **Deferred bugs** section of
  [session-prompts.md](.claude/docs/session-prompts.md) — describing the bug, its impact, **why
  it was deferred**, known risks, and the **conditions under which to revisit** — plus a
  ready-to-paste fix prompt. Keep the list current throughout the project: remove an entry only
  when the bug is fixed, so unresolved issues stay visible and actionable. (Intentional
  R-divergences with no output impact are documented inline / in `progress.md`, not here.)
- **Tone:** strict, technical. No filler.

## Reference docs (read on demand)

- [architecture.md](.claude/docs/architecture.md) — stages, data flow, entry points, contracts.
- [codebase-map.md](.claude/docs/codebase-map.md) — every module by stage, status, R source,
  risk. Use instead of grepping.
- [r-to-python-mapping.md](.claude/docs/r-to-python-mapping.md) — library map, data.table→polars
  idioms, **ranked parity risks**. Read before porting anything.
- [migration-roadmap.md](.claude/docs/migration-roadmap.md) — phases, DAG, parallel tracks,
  effort, parity strategy.
- [full-dataset-parity.md](.claude/docs/full-dataset-parity.md) — the scripted R-vs-Python check
  on the **full 1,339-workbook dataset** (`scripts/parity_full_dataset.py`), how differences are
  judged, and the current measured result. The CI suite only covers the 6-workbook fixture corpus.
- [constants-and-options.md](.claude/docs/constants-and-options.md) — `get_pipeline_constants()`
  surface + `RuntimeOptions` / `WHEP_*` env vars.
- [conventions.md](.claude/docs/conventions.md) — run/test, environment, determinism,
  parallelism, gotchas.
- [common-changes.md](.claude/docs/common-changes.md) — recipes. **Check here first.**
- [guidelines/](.claude/guidelines/) — migration, refactoring, performance, testing, constants.

## Engineering standards

- `snake_case`; full type hints on every public function; Google-style docstrings (the
  roxygen2 analogue; enforced by ruff `D`).
- `pathlib` over `os.path` (enforced by ruff `PTH`). `polars` (immutable, expression-based)
  is the **sole** dataframe engine — no pandas except at a documented IO boundary.
- Validation via `pydantic` (schemas) + guard helpers; errors via
  `whep_digitize.setup.errors`; console/progress via `rich`.
- **Deterministic:** identical inputs + options → identical outputs. Sort via
  `sort_pipeline_stage_df`; seed randomness.
- **No hard-coded literals** — centralize in `setup/constants.py` via
  `get_pipeline_constants()`.
- **No global state**; stages return typed contracts (`contracts.py`).
- **No backward-compat scaffolding** — remove legacy patterns on sight.
- Preserve documented R behavior for parity; don't silently "fix" quirks.

## Run & test

```bash
# CLI
whep-digitize run          # full pipeline    whep-digitize bootstrap   # Stage 0 only

# Python API
python -c "from whep_digitize.pipeline import run_pipeline; run_pipeline(show_view=False)"

# Gates (venv Python; this host has no uv and python != py -3.14)
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy

# Full-dataset R-vs-Python parity (needs R + the production dataset; excluded from `pytest -q`)
.venv/Scripts/python.exe scripts/parity_full_dataset.py
.venv/Scripts/python.exe -m pytest -m slow
```

See [conventions.md](.claude/docs/conventions.md) for the environment specifics
(`py -3.14`, `.venv/`, uv-vs-pip).

## Commands

- `/autocode` — autonomous optimization loop. Config: `autocode.toml`. State:
  [progress.md](.claude/progress.md), [results.tsv](.claude/results.tsv).
