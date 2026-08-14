# Codebase map

Where every function lives, by stage. Use this as a lookup index instead of grepping.

For architecture and data flow see [architecture.md](architecture.md); for the intentional
behaviors and output contracts see [pipeline-behaviors.md](pipeline-behaviors.md); for
constants/options see [constants-and-options.md](constants-and-options.md).

---

## Stage 0 — setup (`whep_digitize.setup`)

| Module | Key API |
|--------|---------|
| `constants.py` | `get_pipeline_constants() -> Constants` (frozen dataclasses; `lru_cache`) |
| `config.py` | `load_pipeline_config(dataset_name, root) -> Config`; `normalize_dataset_name`; `Config`, `Paths` tree |
| `options.py` | `RuntimeOptions` (pydantic-settings; `WHEP_*` env) |
| `directories.py` | `create_required_directories(config)`; `ensure_directories_exist`; `delete_directory_if_exists` |
| `paths.py` | `project_root(start=None)` |
| `errors.py` | `WhepError`, `ConfigurationError`, `ValidationError`, `ContractError` |
| `runner.py` | `run_setup_pipeline(dataset_name, root) -> Config` |

### `setup.helpers`

| Module | Key API |
|--------|---------|
| `strings.py` | `normalize_text`, `normalize_string` (series), `normalize_filename`, `transliterate_ascii_lower` (the NFD diacritic-strip policy) |
| `numeric.py` | `coerce_numeric`, `coerce_numeric_series`, `format_double_fixed` (15-sig-fig fixed-notation double rendering) |
| `sorting.py` | `sort_pipeline_stage_df(frame, sort_columns=None)` |
| `frames.py` | `drop_na_value_rows(frame, value_column, *, enabled)` |
| `checkpoints.py` | `save_checkpoint`, `load_checkpoint`, `clear_checkpoints` (parquet/pickle); wired into the import runner only |
| `time_format.py` | `format_elapsed_time(seconds)` |
| `tokens.py` | `extract_yearbook(parts)`, `extract_commodity(parts, start_index=None)` |
| `assertions.py` | `require(condition, message)`, `require_columns(...)` |
| `console.py` | `alert_info/success/warning/error`, `get_console` (rich; ASCII-safe) |
| `progress.py` | `stage_progress(label, total, *, enabled)` ctx mgr → `StageProgress` (`step`/`pulse`); gated `rich.progress` bars |

---

## Shared — `whep_digitize` top level

| Module | Key API |
|--------|---------|
| `contracts.py` | `ImportResult`, `ImportDiagnostics`, `PostproResult`, `PostproDiagnostics`, `LayerDiagnostics`, `MultiPassDiagnostics`, `ExportResult`, `assert_export_paths_contract` |
| `pipeline.py` | `run_pipeline(*, show_view, dataset_name, root, options) -> ExportResult` |
| `cli.py` | `app` (typer): `run`, `bootstrap` |

---

## Stage 1 — ingest (`whep_digitize.ingest`)

Public: `runner.run_import_pipeline(config, options=None, current_year=None) -> ImportResult`
(discover → fused read+transform → drop-null → validate-by-document → consolidate → sort).

| Module | Key API |
|--------|---------|
| `file_io/discovery.py` | `discover_files`, `discover_pipeline_files` |
| `file_io/metadata.py` | `extract_file_metadata`, `build_empty_file_metadata` |
| `reading/read_utils.py` | `ReadResult`, `SafeReadResult`, `safe_execute_read`, `create_empty_read_result`, `has_read_errors`, `normalize_pipeline_read_result`, `build_read_error` |
| `reading/sheet_read.py` | `read_excel_sheet`, `read_file_sheets`, `compute_non_empty_base_rows`, `restore_numeric_text_precision` (each sheet is read twice — all-as-text + typed — to repair rounded float text; see pipeline-behaviors) |
| `reading/header_normalization.py` | `normalize_header_name`, `normalize_header_names`, `validate_header_normalization`, `resolve_canonical_header_renames`, `HeaderRenames` |
| `reading/batching.py` | `split_workbook_batches`, `resolve_import_workbook_batch_size`, `resolve_import_effective_workers`, `read_workbook_batch`, `BatchReadResult` |
| `transform/transform_utils.py` | `identify_year_columns`, `normalize_key_fields`, `convert_year_columns` |
| `transform/reshape.py` | `reshape_to_long` (unpivot), `add_metadata`, `transform_file_df`, `resolve_commodity_name`, `build_empty_transform_result`, `TransformResult` |
| `transform/processing.py` | `read_transform_pipeline_files` (fused, `ProcessPoolExecutor`, deterministic + sequential fallback), `transform_single_file`, `ReadTransformResult` |
| `output/validate.py` | `validate_long_df_by_document`, `ValidationResult` |
| `output/consolidate.py` | `consolidate_audited_df`, `validate_output_column_order`, `ConsolidateResult` |
| `runner.py` | `run_import_pipeline` (incl. `rich` progress + the opt-in checkpoint cache) |

---

## Stage 2 — postpro (`whep_digitize.postpro`)

Public: `runner.run_postpro_pipeline(raw, config, dataset_name=None, options=None) -> PostproResult`
(audit → resolve output roots → templates → collect-preflight → assert-preflight → clean →
standardize → harmonize → persist; each layer canonically sorted). The **rule engine** is the
algorithmic core.

| Module | Key API |
|--------|---------|
| `audit/audit.py` | `audit_data_output` (value→Float64; rows failing validation retained), `AuditResult` |
| `audit/validation.py` | non-empty + numeric-string validators, master validation |
| `audit/config.py` | audit config + findings schema |
| `audit/export.py` | styled invalid-cell highlight (openpyxl) |
| `utilities/stage_definitions.py` | canonical rule columns, stage names + value columns |
| `utilities/output_roots.py` | resolve/create audit subtree, `PostproOutputPaths` |
| `utilities/diagnostics.py` | `build_layer_diagnostics` → `LayerDiagnostics` |
| `utilities/templates.py` | rule templates; `read_rule_table` (all-text; sheet match), payload discovery |
| `utilities/payload_cache.py` | 2-level payload cache (off by default; pickle disk) |
| `clean_harmonize/layer_runner.py` | `run_rule_stage_layer_batch` (multi-pass driver), `StageLayerResult` |
| `clean_harmonize/controls_cache.py` | multi-pass controls + two-tier cycle detection |
| `clean_harmonize/stage_inputs.py` | `;`-token canonicalization; drop empty footnotes |
| `rule_engine/matching_strategy.py` | key encode/decode, strategy config |
| `rule_engine/matching_values.py` | tokenized match (all columns) + `#EXACT#` directive, concat merge, change count |
| `rule_engine/target_apply.py` | `last_rule_wins` + overwrite events, `concatenate` |
| `rule_engine/conditional_group.py` | keyed cartesian join, source+target scatter, audit |
| `rule_engine/footnote_rules.py` | explode→match→resolve→reconstruct |
| `rule_engine/schema_validation.py` | coerce/validate rules, conditional dictionary |
| `rule_engine/payload_application.py` | `apply_rule_payload`, execution plan |
| `standardize_units/engine.py` | `apply_standardize_rules` (fold, 2-stage, affine), `StandardizeResult` |
| `standardize_units/rules_setup.py` | aliasing, validation, `prepare_standardize_rules` |
| `standardize_units/aggregation.py` | duplicate-group sum (all-null→null), idempotent |
| `standardize_units/orchestration.py` | `run_standardize_units_layer_batch` + rule readers + audit, `StandardizeLayerResult` |
| `diagnostics/preflight.py` | `collect_postpro_preflight`, `assert_postpro_preflight` |
| `diagnostics/output.py` | `build_postpro_diagnostics`, `persist_postpro_audit`, overwrite subset (group-by row + join), multi-sheet xlsx |
| `diagnostics/rule_summaries.py` | clean/harmonize matched + unmatched summaries (null-safe anti-join) |
| `diagnostics/standardize_summaries.py` | standardize summaries (normalized-key counts branch) |

---

## Stage 3 — export (`whep_digitize.export`)

Public: `runner.run_export_pipeline(config, result, *, raw=None, overwrite=True) -> ExportResult`
(builds the `whep_data_{raw,clean,normalize,harmonize}` mapping, ensures the export dirs, writes
processed-data TSVs + unique-list workbooks, asserts the paths contract).

| Module | Key API |
|--------|---------|
| `processed_data/layers.py` | `collect_layer_tables_for_export` (name-based detect from an explicit mapping; excludes `_wide_raw`/`_post_processed`; sorted) |
| `processed_data/export.py` | `export_processed_data` (harmonize-only default), `build_processed_export_path`, `write_processed_table` (platform eol + the shared double formatter) |
| `lists/unique_values.py` | `LISTS_SHEET_ORDER`, `infer_layer_sheet_name`, `compute_unique_column_values` (drop-null, code-point sort, `(blank)` prepend), `build_column_lists_export_path`, `build_layer_tables_by_sheet`, `collect_union_columns` |
| `lists/merge.py` | `resolve_lists_export_columns`, `resolve_list_sheet_payloads` (identical-layer merge, fixed sheet order) |
| `lists/write.py` | `build_column_unique_cache`, `write_column_lists_workbook` (no-header multi-sheet `xlsxwriter`), `export_lists` (filename-collision guard) |

---

## Tests (`tests/`, pytest)

`tests/conftest.py` provides the `project_dir`, `config`, and `sample_long_df` fixtures.
Per-stage suites mirror the package layout: `tests/setup/`, `tests/contracts/`, `tests/ingest/`,
`tests/postpro/`, `tests/export/`, `tests/parity/`. `tests/test_pipeline_e2e.py` exercises the
top-level `run_pipeline` orchestration.

`tests/parity/` asserts pipeline output against the **frozen reference goldens** committed under
`tests/golden/` (immutable, no regeneration path — see `tests/golden/README.md` and
[pipeline-behaviors.md](pipeline-behaviors.md)). `tests/parity/goldens.py` declares the expected
export names per module; `test_goldens_present.py` fails loudly if a golden is missing, because
the individual tests skip in that case. Mark such tests `@pytest.mark.parity`.

Everything runs against the **6-workbook fixture corpus**, never the production dataset — see
[architecture.md](architecture.md) → *Datasets*.

## Benchmarks (`.claude/bench/`)

`bench.py` times the full `run_pipeline` on a frozen dataset and prints `PIPELINE_SECONDS: <n>`
(min over `WHEP_BENCH_ITERATIONS` runs). It is the autocode `performance` metric
(`autocode.toml`) and is read-only to the autocode loop.
