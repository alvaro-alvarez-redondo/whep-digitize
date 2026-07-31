# Constants & options

## Constants — `whep_digitize.setup.constants`

**Authoritative source:** `src/whep_digitize/setup/constants.py`. Access via
`get_pipeline_constants() -> Constants` (memoized with `functools.lru_cache`, the analogue
of the R global cache). The result is an immutable tree of frozen dataclasses; sequences
are tuples, mappings are `MappingProxyType`. **Treat as immutable.**

```python
from whep_digitize.setup.constants import get_pipeline_constants
c = get_pipeline_constants()
c.sorting.stage_row_order        # the 12-column canonical order
c.postpro.canonical_rule_columns # the 6 rule columns
```

### Groups

| Attribute | Holds |
|-----------|-------|
| `dataset_default_name` | `"whep_data_raw"` |
| `na_placeholder` / `na_match_key` | `"..NA_INTERNAL.."` / `"..NA_MATCH_KEY.."` |
| `patterns` | regexes (year column, header normalization, footnote, file extension, …) |
| `header_normalization` | replacements + `canonical_aliases` (`country`→`polity`) |
| `performance` | `import_workbook_batch_size=32`, `import_parallel_workers="auto"`, `import_parallel_workers_auto_max=8`, `import_future_scheduling=4`, normalize thresholds |
| `defaults` | `unknown_document`, `unknown_commodity`, `list_blank_label`, `unknown_filename`, `value_column`, `notes_value=None` |
| `object_names` | canonical layer object names (`whep_data_raw/_clean/_normalize/_harmonize`) |
| `columns` | `base`, `id_vars` (R `columns$id`), `value`, `system` |
| `sorting.stage_row_order` | the 12-column canonical order |
| `files` | workbook file names |
| `paths` | relative dir names under `data/` |
| `checkpoints` | `import_stage_name="import_pipeline"`, `.parquet`/`.pkl` suffixes, save/restore status text |
| `tokens.commodity_start_index` | `7` (1-based, R convention) |
| `time_units` | `seconds_per_minute`, `seconds_per_hour` |
| `postpro` | rule columns, wildcard `__ANY__`, `rule_match_normalization`, `target_update_strategies` (default `last_rule_wins`; `notes`→`concatenate`), `multi_pass` (max 10, `cycle_policy="warn"`), `runtime_cache`/`schema_validation_cache` (both off), audit file names |
| `export_config` | `lists_to_export`, `export_layers=("harmonize",)`, `processed_suffix=".tsv"`, `error_highlight` style |
| `progress` | stage labels + per-step messages (presentation left to `rich`) |
| `fixed_export_columns` / `audit_columns` | export/audit column tuples |

### Deliberate divergences from the R constants

- **`export_config.processed_suffix = ".tsv"`** — the R `data_suffix=".xlsx"` was dead code
  (processed export always wrote `.tsv`).
- **Single `defaults` group** — R confusingly split operational defaults across
  `config$defaults` (only `notes_value`) and `constants$defaults`. Here all live in
  `Defaults`; `notes_value=None`.
- **Dropped R runtime-only constants** — source-time auto-run option names, the declared
  R-package list (`uv` owns dependencies), the ANSI progress palette (`rich` themes).
- **`runtime_cache.cache_file_name`** ends `.parquet` (R used `.rds`).

## Runtime options — `whep_digitize.setup.options.RuntimeOptions`

A `pydantic-settings` model, overridable via `WHEP_*` environment variables. Pass an
instance to `run_pipeline(options=...)` or let stages construct the default.

| Option | Env var | Default | Controls |
|--------|---------|---------|----------|
| `drop_na_values` | `WHEP_DROP_NA_VALUES` | `True` | drop null-`value` rows during import |
| `progress_enabled` | `WHEP_PROGRESS_ENABLED` | `True` | show the `rich` progress display |
| `checkpointing_enabled` | `WHEP_CHECKPOINTING_ENABLED` | `False` | cache the import stage: restore a prior `ImportResult` instead of re-running, save one on completion |
| `import_parallel_workers` | `WHEP_IMPORT_PARALLEL_WORKERS` | `"auto"` | import worker count (`"auto"`→`min(8, cpu-1)`; `1`=sequential) |
| `export_parallel_workers` | `WHEP_EXPORT_PARALLEL_WORKERS` | `1` | unique-list workbook-write worker count (`1`=sequential; `"auto"`/`N`=deterministic `ProcessPoolExecutor`) |

`checkpointing_enabled` is wired in `ingest.runner.run_import_pipeline` only — as in R, postpro
and export do not checkpoint. The restore happens before file discovery, so a hit skips the whole
stage (including its empty-folder abort); files land in `data/.checkpoints/` (git-ignored). It is a
cache of a prior run, so it never changes first-run output — clear it with
`helpers.checkpoints.clear_checkpoints` when the raw inputs change.

The project-root override `WHEP_PROJECT_ROOT` (read by `setup.paths.project_root`) forces
where `data/` is resolved.

**Dropped from R:** `whep.run_*_pipeline.auto` — Python has no source-on-import execution,
so there is nothing to auto-run; stages are explicit calls.
