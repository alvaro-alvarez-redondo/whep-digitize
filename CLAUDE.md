# CLAUDE.md

whep-digitize — the WHEP digitization pipeline. A deterministic four-stage Python/Polars
pipeline that turns WHEP source workbooks into published datasets:
setup (0) → ingest (1) → postpro (2) → export (3).

Input is Excel workbooks under `data/input/raw/`; output is processed TSVs plus unique-value
list workbooks under `data/output/`. All four stages are implemented and covered by tests.

## How to work

- **Act autonomously.** Decide when context is sufficient; default to action. Ask only when
  a decision is ambiguous, irreversible, high-impact, or under-specified. Document assumptions.
- **Read before changing semantics.** [pipeline-behaviors.md](.claude/docs/pipeline-behaviors.md)
  records the behaviors that *look* like bugs and are deliberate. Changing one changes published
  data.
- **Reuse project context.** Read `.claude/docs/` (kept current) instead of rescanning. Start
  with [codebase-map.md](.claude/docs/codebase-map.md) to find code and
  [common-changes.md](.claude/docs/common-changes.md) for recipes.
- **Use `/autocode`** for perf/quality/test work.
- **Deliver complete solutions.** Don't stop at partial work; a change is done only with passing
  tests + gates.
- **One concern per change.** Focused diffs. Delete every temporary file the moment it is no
  longer needed — never defer to commit time, never commit one (temp-file policy in
  [conventions.md](.claude/docs/conventions.md)).
- **Tests are ground truth.** Every behavior change ships with tests. Never lower the pass rate.
  The frozen goldens under `tests/golden/` are immutable and have no regeneration path — a
  failing parity test means the pipeline's behavior changed.
- **Log deferred bugs (mandatory).** Whenever you identify a bug but intentionally do **not**
  fix it in the same session, you MUST add an entry to
  [deferred-bugs.md](.claude/docs/deferred-bugs.md) — the bug, its impact, **why it was
  deferred**, known risks, the **conditions under which to revisit**, and a ready-to-paste fix
  prompt. Remove an entry only when the bug is fixed, so unresolved issues stay visible.
  (Deliberate behaviors with no defect are documented in `pipeline-behaviors.md`, not here.)
- **Tone:** strict, technical. No filler.

## Reference docs (read on demand)

- [architecture.md](.claude/docs/architecture.md) — stages, data flow, entry points, contracts.
- [codebase-map.md](.claude/docs/codebase-map.md) — every module by stage. Use instead of grepping.
- [pipeline-behaviors.md](.claude/docs/pipeline-behaviors.md) — the intentional behaviors and
  output contracts. **Read before changing pipeline semantics.**
- [constants-and-options.md](.claude/docs/constants-and-options.md) — `get_pipeline_constants()`
  surface + `RuntimeOptions` / `WHEP_*` env vars.
- [conventions.md](.claude/docs/conventions.md) — run/test, environment, determinism,
  parallelism, gotchas.
- [common-changes.md](.claude/docs/common-changes.md) — recipes. **Check here first.**
- [deferred-bugs.md](.claude/docs/deferred-bugs.md) — known unfixed bugs and when to revisit.
- [guidelines/](.claude/guidelines/) — refactoring, performance, testing, constants.

## Engineering standards

- `snake_case`; full type hints on every public function; Google-style docstrings (enforced by
  ruff `D`).
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
- **Don't silently "fix" a documented behavior.** If it is in
  [pipeline-behaviors.md](.claude/docs/pipeline-behaviors.md), it is intentional.

## Run & test

```bash
# CLI
py -3.14 -m whep_digitize            # full pipeline
py -3.14 -m whep_digitize bootstrap  # Stage 0 only

# Python API
py -3.14 -c "from whep_digitize.pipeline import run_pipeline; run_pipeline(show_view=False)"

# Gates (this host has no uv and python != py -3.14)
py -3.14 -m pytest -q
py -3.14 -m ruff check .
py -3.14 -m mypy
```

See [conventions.md](.claude/docs/conventions.md) for the environment specifics
(`py -3.14`, uv-vs-pip).

## Commands

- `/autocode` — autonomous optimization loop. Config: `autocode.toml`. State:
  [progress.md](.claude/progress.md), [results.tsv](.claude/results.tsv).
