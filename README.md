# whep-digitize

The **WHEP digitization pipeline** — a deterministic, four-stage
Python/[Polars](https://pola.rs) pipeline that turns WHEP source workbooks into clean,
harmonized, unit-standardized tabular data plus unique-value reference lists.

```
setup (0)  ->  ingest (1)  ->  postpro (2)  ->  export (3)
 constants       discover        audit             processed TSV
 config          read (xlsx)     clean             unique lists (xlsx)
 helpers         wide->long      standardize units
 directories     validate        harmonize
```

Input is Excel workbooks under `data/import/raw/`; output lands in `data/export/`.

## Design

- **Deterministic.** Identical inputs and options produce identical outputs, byte for byte —
  including under parallelism, where results are independent of worker count.
- **One engine.** `polars` (immutable, expression-based) is the sole dataframe engine.
- **Typed stage contracts.** Each stage returns a frozen result object (`contracts.py`); nothing
  is published through global state.
- **Behavior pinned by frozen reference outputs.** `tests/golden/` holds immutable expected
  output that the test suite asserts against, so a semantic change cannot pass unnoticed.

Statically typed (`mypy --strict`), linted and formatted (`ruff`), packaged with a lockfile
(`uv`), and tested in CI across Python 3.11–3.13.

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
whep-digitize bootstrap                 # Stage 0 only (build the directory tree)

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
  setup/          # Stage 0 — constants, config, directories, helpers
  ingest/         # Stage 1 — file_io, reading, transform, output
  postpro/        # Stage 2 — audit, clean/harmonize, rule_engine, standardize_units
  export/         # Stage 3 — processed_data, lists
  pipeline.py     # run_pipeline orchestrator
  cli.py          # typer CLI
  contracts.py    # shared typed result contracts
tests/            # pytest suites, mirroring the package layout
  fixtures/       # frozen inputs
  golden/         # frozen expected outputs (immutable)
.claude/          # working docs, guidelines, benchmark
```

## Engineering standards

`snake_case`; type hints on every public function; Google-style docstrings; `pathlib` over
`os.path`; `polars` as the sole dataframe engine; deterministic outputs; no hard-coded literals
(centralized in [`setup/constants.py`](src/whep_digitize/setup/constants.py)); validation via
`pydantic`/guards; errors and progress via `rich`.

Before changing pipeline semantics, read
[.claude/docs/pipeline-behaviors.md](.claude/docs/pipeline-behaviors.md) — it records the
behaviors that look like bugs and are deliberate. See [CLAUDE.md](CLAUDE.md) and
[.claude/docs/](.claude/docs/) for architecture and conventions.

## License

MIT.
