# whep-digitize

Python/[Polars](https://pola.rs) port of the **WHEP digitization pipeline**
(the R project [`whep-digitalization`](https://github.com/eduaguilera/whep)).

A deterministic, four-stage pipeline that turns WHEP source workbooks into clean,
harmonized, unit-standardized tabular data plus unique-value reference lists.

```
setup (0)  ->  ingest (1)  ->  postpro (2)  ->  export (3)
 constants       discover        audit             processed TSV
 config          read (xlsx)     clean             unique lists (xlsx)
 helpers         wide->long      standardize units
 directories     validate        harmonize
```

> **Status: foundation.** Stage 0 (`setup`) is implemented and tested. Stages 1–3
> are scaffolded with typed contracts and are being migrated incrementally. See the
> [migration roadmap](.claude/docs/migration-roadmap.md) for the plan and current state.

---

## Why this port exists

The R pipeline is mature and correct but hard to onboard, package, and deploy. This
Python port reproduces the same outputs **byte-for-byte — except for one intentional
divergence** (verified by parity tests against R golden files): string/header normalization
follows a documented policy (NFD diacritic strip + lowercase) instead of R's ICU
`Latin-ASCII`, which changes **~13 rows on the full dataset**, leaving value sums and row
counts unchanged. Byte-identity was verified 2026-07-24, before that policy was accepted on
2026-07-29; see [r-to-python-mapping.md](.claude/docs/r-to-python-mapping.md) risk #1.

In exchange the port gains: a real package + lockfile (`uv`), static typing (`mypy`),
one fast columnar engine (`polars`), and a modern test/CI story.

The migration is designed to be **incremental and parallelizable** — each R module maps
to a Python module with a fixed input/output contract, so stages and sub-modules can be
ported independently and validated in isolation.

## Requirements

- **Python ≥ 3.11**
- [**uv**](https://docs.astral.sh/uv/) (recommended) or `pip` + `venv`

## Setup

### With uv (recommended)

```bash
uv sync --extra dev      # creates .venv and installs everything from uv.lock
uv run whep-digitize --help
```

### With pip

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on POSIX
pip install -e ".[dev]"
```

> On this Windows host, Python is invoked via the launcher: `py -3.14`. See
> [.claude/docs/conventions.md](.claude/docs/conventions.md) for environment notes.

## Usage

```bash
# CLI
whep-digitize run                       # run the full pipeline
whep-digitize run --no-view             # headless

# Python API
python -c "from whep_digitize.pipeline import run_pipeline; run_pipeline(show_view=False)"
```

## Development

```bash
uv run pytest            # tests (ground-truth metric)
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy              # type-check
```

The autonomous optimization loop is configured in [`autocode.toml`](autocode.toml).

## Layout

```
src/whep_digitize/
  setup/          # Stage 0 — constants, config, directories, helpers  [IMPLEMENTED]
  ingest/         # Stage 1 — file_io, reading, transform, output       [scaffold]
  postpro/        # Stage 2 — audit, clean/harmonize, rule_engine, ...   [scaffold]
  export/         # Stage 3 — processed_data, lists                      [scaffold]
  pipeline.py     # run_pipeline orchestrator
  cli.py          # typer CLI
  contracts.py    # shared typed result contracts
tests/            # pytest suites, mirroring the package layout
.claude/          # AI working layer: docs, guidelines, skills, roadmap
```

## Engineering standards

`snake_case`; type hints on every public function; Google-style docstrings (mirroring the
R project's per-function roxygen docs); `pathlib` over `os.path`; `polars` (immutable,
expression-based) as the sole dataframe engine; deterministic outputs (identical inputs +
options → identical outputs); no hard-coded literals (centralized in
[`setup/constants.py`](src/whep_digitize/setup/constants.py)); validation via
`pydantic`/guards; errors and progress via `rich`.

See [CLAUDE.md](CLAUDE.md) and [.claude/docs/](.claude/docs/) for the full architecture,
conventions, and the R→Python mapping.

## License

MIT.
