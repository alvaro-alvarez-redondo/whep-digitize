# Architecture

## Overview

A deterministic, package-oriented Python pipeline (the port of the R `whep-digitalization`
script pipeline). `whep_digitize.pipeline.run_pipeline` orchestrates four stages in fixed
order by **explicit function calls** (no source-on-import side effects):

```
setup (0)  ->  ingest (1)  ->  postpro (2)  ->  export (3)
```

The single dataframe engine is **polars** (columnar, immutable, multi-threaded) — the
Python analogue of R's `data.table`. Each stage returns a typed, frozen result object
(see [contracts](#contracts)); nothing is written to a global namespace.

## Stage layout

| Stage | Python package | R source | Responsibility |
|-------|----------------|----------|----------------|
| 0 — setup | `whep_digitize.setup` | `r/0-general_pipeline/` | constants, config, directories, helpers |
| 1 — ingest | `whep_digitize.ingest` | `r/1-import_pipeline/` | discover, read, wide→long, validate |
| 2 — postpro | `whep_digitize.postpro` | `r/2-postpro_pipeline/` | audit, clean, standardize units, harmonize |
| 3 — export | `whep_digitize.export` | `r/3-export_pipeline/` | processed TSVs + unique-list workbooks |

`ingest` is the stage-1 name because `import` is a Python keyword. Sub-packages mirror the
R numbered subdirectories (minus the numeric prefixes, which encoded R's `source()` order —
irrelevant under explicit imports). See [codebase-map.md](codebase-map.md).

## Data flow

```
Excel workbooks (data/import/raw/**.xlsx)
   │  discover → read (all-text) → wide→long unpivot → validate (by document)
   ▼
ImportResult(data=long df, wide_raw=wide df, diagnostics)
   │  run_postpro_pipeline: audit → clean → standardize units → harmonize
   ▼
PostproResult(harmonize, clean, normalize, diagnostics)
   │  run_export_pipeline: processed TSV + unique-list xlsx
   ▼
ExportResult(processed_paths, lists_paths)
```

### Canonical column order

```
hemisphere, continent, polity, commodity, variable, unit, year, value,
notes, footnotes, yearbook, document
```

Data is **string-typed through import** (every column read as text). The one downstream
exception: `postpro.audit` parses `value` to `Float64` (polars `cast(Float64,
strict=False)`, the analogue of `readr::parse_double`); from the clean layer onward `value`
is a float while every other column stays string. Null-`value` rows are dropped by default
(`RuntimeOptions.drop_na_values`) during import, before that coercion.

## Datasets — the two that matter (do not conflate)

Parity is asserted against **two different input sets**, and every parity claim in these docs
must say which one it means.

| | **Fixture corpus** | **Full production dataset** |
|---|---|---|
| Location | `tests/fixtures/corpus/` (committed) | `data/import/raw/` (and the R project's `data/1-import/10-raw_import/`) |
| Size | **6 workbooks** (~37 KB) | **1,339 workbooks** (verified 2026-07-30) |
| Contents | one smallest-per-category workbook: crops / livestock / population / inputs / land / trade | every WHEP source workbook |
| Versioned? | yes — committed, immutable | no — lives in Nextcloud and **grows over time** |
| Parity coverage | **automated**: `tests/parity/` + `tests/test_pipeline_e2e.py`, run in CI against committed R goldens (no R install needed) | **automated but opt-in**: `scripts/parity_full_dataset.py`, needs an executable R + the dataset (neither exists in CI) |
| What it proves | per-module and per-stage behaviour on representative inputs | end-to-end byte-parity of the real deliverable |

The fixture corpus is the *routine* gate; it is small by design, so **it cannot catch scale- or
data-dependent divergence**. The full dataset is the real parity target, and reaching it requires
R — R is the parity oracle and there is no reference output without running it. See
[full-dataset-parity.md](full-dataset-parity.md).

Because the production dataset grows, any count quoted here is a measurement with a date, not a
constant. Re-measure with:

```bash
find data/import/raw -name '*.xlsx' | wc -l
```

## Entry points

- `run_pipeline(*, show_view=False, dataset_name=None, root=None, options=None) -> ExportResult`
  — the top-level orchestrator (`whep_digitize/pipeline.py`).
- `setup.runner.run_setup_pipeline(dataset_name=None, root=None) -> Config`.
- `ingest.runner.run_import_pipeline(config, options=None) -> ImportResult`.
- `postpro.runner.run_postpro_pipeline(raw, config, dataset_name=None, options=None) -> PostproResult`.
- `export.runner.run_export_pipeline(config, result, *, overwrite=True) -> ExportResult`.

CLI: `whep-digitize run` (full pipeline) and `whep-digitize bootstrap` (Stage 0 only).

## Contracts

Stage boundaries are **typed frozen dataclasses** in `whep_digitize/contracts.py`, replacing
two R idioms: assigning results into the global environment, and carrying diagnostics as
`data.table` `attr()`s. Fixing these up front is what makes the migration parallelizable —
a stage can be built and parity-tested against fixtures as long as it honors its result type.

| Contract | Replaces (R) | Invariant |
|----------|--------------|-----------|
| `ImportResult` | `list(data, wide_raw, diagnostics)` | `data`/`wide_raw` are `pl.DataFrame`; diagnostics typed |
| `PostproResult` | harmonized dt + `attr(pipeline_diagnostics)` + `attr(stage_*)` | three layer frames + typed diagnostics |
| `ExportResult` | `list(processed_paths, lists_paths)` | both non-empty `Mapping[str, Path]` (`assert_export_paths_contract`) |

## Deliberate divergences from R (Python-native)

- **No auto-run on import.** R auto-executed on `source()`; Python modules are import-safe
  and stages run via explicit calls. The `whep.run_*_pipeline.auto` flags are dropped.
- **Immutable frames.** polars is immutable; R's by-reference `data.table::set`/`:=` mutation
  becomes functional pipelines (join-back + `when/then`).
- **Typed results, no global state.** See [contracts](#contracts).
- **`uv` + `pyproject.toml`** replace `renv` and the R dependency-audit stage.
- **Fixed R foot-guns:** the dead `export_config$data_suffix=".xlsx"` is renamed
  `processed_suffix=".tsv"`; the `config$defaults`/`constants$defaults` name collision is
  removed. See [constants-and-options.md](constants-and-options.md).
- **Policy-based string normalization** — the one divergence that reaches the output.
  `helpers.strings.transliterate_ascii_lower` implements the documented POLICY (NFD diacritic
  strip + lowercase; the caller then drops non-alphanumerics), **not** R's ICU `Latin-ASCII`.
  Pipeline output is therefore byte-identical to R *except* here: ~13 rows on the full dataset
  (value sums and row counts unchanged). Accepted 2026-07-29, after byte-identity was verified
  2026-07-24; see [r-to-python-mapping.md](r-to-python-mapping.md) risk #1 and the parity
  timeline in [migration-roadmap.md](migration-roadmap.md).

## Data layout (gitignored, under `data/`)

- `data/import/` — `raw` (input `.xlsx`), then `clean` /
  `standardize` / `harmonize`.
- `data/postpro/` — `audit`, `diagnostics`, `templates`, `runtime_cache` (the audit
  subtree; the `2-postpro` root is created lazily as their parent).
- `data/export/` — `processed` (**TSV**), `lists` (**xlsx** `unique_*.xlsx`).
