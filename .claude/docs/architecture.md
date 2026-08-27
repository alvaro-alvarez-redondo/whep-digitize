# Architecture

## Overview

A deterministic, package-oriented Python pipeline. `whep_digitize.pipeline.run_pipeline`
orchestrates four stages in fixed order by **explicit function calls** (no import-time side
effects):

```
setup (0)  ->  ingest (1)  ->  postpro (2)  ->  export (3)
```

The single dataframe engine is **polars** (columnar, immutable, multi-threaded). Each stage
returns a typed, frozen result object (see [contracts](#contracts)); nothing is written to a
global namespace.

## Stage layout

| Stage | Python package | Responsibility |
|-------|----------------|----------------|
| 0 — setup | `whep_digitize.setup` | constants, config, directories, helpers |
| 1 — ingest | `whep_digitize.ingest` | discover, read, wide→long, validate |
| 2 — postpro | `whep_digitize.postpro` | audit, clean, standardize units, harmonize |
| 3 — export | `whep_digitize.export` | processed TSVs + unique-list workbooks |

`ingest` / `export` name the *stage actions*; `input` / `output` name the **data** and its
locations (`data/input/`, `data/output/`, `paths.data.input`, `paths.data.output`). See
[codebase-map.md](codebase-map.md) for the module index.

## Data flow

```
Excel workbooks (data/input/raw/**.xlsx)
   │  discover → read (all-text) → wide→long unpivot → validate (by document)
   ▼
InputResult(data=long df, wide_raw=wide df, diagnostics)
   │  run_postpro_pipeline: audit → clean → standardize units → harmonize
   ▼
PostproResult(harmonize, clean, normalize, diagnostics)
   │  run_export_pipeline: processed TSV + unique-list xlsx
   ▼
OutputResult(processed_paths, lists_paths)
```

### Canonical column order

```
hemisphere, continent, polity, commodity, variable, unit, year, value,
notes, footnotes, yearbook, document
```

Data is **string-typed through import** (every column read as text). The one downstream
exception: `postpro.audit` parses `value` to `Float64` (polars `cast(Float64, strict=False)`);
from the clean layer onward `value` is a float while every other column stays string.
Null-`value` rows are dropped by default (`RuntimeOptions.drop_na_values`) during ingest, before
that coercion.

## Datasets — the two that matter (do not conflate)

| | **Fixture corpus** | **Full production dataset** |
|---|---|---|
| Location | `tests/fixtures/corpus/` (committed) | `data/input/raw/` |
| Size | **6 workbooks** (~37 KB) | **1,339 workbooks** (measured 2026-07-31) |
| Contents | one smallest-per-category workbook: crops / livestock / population / inputs / land / trade | every WHEP source workbook |
| Versioned? | yes — committed, immutable | no — lives in Nextcloud and **grows over time** |
| Used by | the whole test suite, including `tests/parity/` and `tests/test_pipeline_e2e.py` | real runs (`whep-digitize run`) and the benchmark |

The fixture corpus is the routine gate. It is small by design, so **it cannot catch scale- or
data-dependent problems** — an issue that only appears at production scale will not surface until
a real run. Keep that limit in mind when a change touches reading, parsing, or numeric handling.

Because the production dataset grows, any count quoted here is a measurement with a date, not a
constant. Re-measure with:

```bash
find data/input/raw -name '*.xlsx' | wc -l
```

## Entry points

- `run_pipeline(*, show_view=False, dataset_name=None, root=None, options=None) -> OutputResult`
  — the top-level orchestrator (`whep_digitize/pipeline.py`).
- `setup.runner.run_setup_pipeline(dataset_name=None, root=None) -> Config`.
- `ingest.runner.run_ingest_pipeline(config, options=None) -> InputResult`.
- `postpro.runner.run_postpro_pipeline(raw, config, dataset_name=None, options=None) -> PostproResult`.
- `export.runner.run_export_pipeline(config, result, *, overwrite=True) -> OutputResult`.

CLI: `whep-digitize run` (full pipeline) and `whep-digitize bootstrap` (Stage 0 only).

## Contracts

Stage boundaries are **typed frozen dataclasses** in `whep_digitize/contracts.py`. A stage can be
built and tested in isolation as long as it honors its result type.

| Contract | Invariant |
|----------|-----------|
| `InputResult` | `data`/`wide_raw` are `pl.DataFrame`; diagnostics typed |
| `PostproResult` | three layer frames (`clean`, `normalize`, `harmonize`) + typed diagnostics |
| `OutputResult` | both path maps non-empty `Mapping[str, Path]` (`assert_output_paths_contract`) |

## Design decisions

- **No import-time execution.** Modules are import-safe; stages run via explicit calls.
- **Immutable frames.** polars frames are never mutated in place; updates are functional
  pipelines (join-back + `when/then`).
- **Typed results, no global state.** See [contracts](#contracts).
- **`uv` + `pyproject.toml`** own dependencies and the lockfile.
- **Policy-based string normalization.** `helpers.strings.transliterate_ascii_lower` implements a
  documented policy (NFD diacritic strip + lowercase; the caller then drops non-alphanumerics).
  It decides which post-processing rules fire, so it is a behavioral contract — see
  [pipeline-behaviors.md](pipeline-behaviors.md).

## Data layout (gitignored, under `data/`)

- `data/input/` — `raw` (input `.xlsx`), then `clean` / `standardize` / `harmonize`.
- `data/postpro/` — `audit`, `diagnostics`, `templates`, `runtime_cache` (the audit
  subtree; the `2-postpro` root is created lazily as their parent).
- `data/output/` — `processed` (**TSV**), `lists` (**xlsx** `unique_*.xlsx`).
