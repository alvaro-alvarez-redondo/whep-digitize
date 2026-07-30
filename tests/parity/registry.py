"""Registry of R→Python golden captures.

Each entry declares how to reproduce one R module's output from the frozen fixtures. Add a
new :class:`CaptureSpec` here when standing up parity for another module; the harness and the
``capture.py`` CLI pick it up automatically.
"""

from __future__ import annotations

from r_harness import CaptureSpec

# R general-pipeline sources needed for the string helpers: constants first (defines
# get_pipeline_constants), then the string-normalization module itself.
_GENERAL_CONSTANTS = "r/0-general_pipeline/01-setup/01-constants.R"
_STRING_NORMALIZATION = "r/0-general_pipeline/02-helpers/02-string-normalization.R"
# Ingest file-metadata: assertions (assert_or_abort) then the metadata module. The atomic
# write_golden captures each output column of extract_file_metadata separately.
_ASSERTIONS = "r/0-general_pipeline/02-helpers/02-assertions.R"
_FILE_METADATA = "r/1-import_pipeline/10-file_io/10-metadata.R"
_HEADER_NORMALIZATION = "r/1-import_pipeline/11-reading/11-header-normalization.R"
_DATA_TABLE = "r/0-general_pipeline/02-helpers/02-data-table.R"  # ensure_data_table
_DATA_CLEANING = "r/0-general_pipeline/02-helpers/02-data-cleaning.R"  # drop_na_value_rows
_READ_UTILS = "r/1-import_pipeline/11-reading/11-read-utils.R"
_SHEET_READ = "r/1-import_pipeline/11-reading/11-sheet-read.R"
_TRANSFORM_UTILS = "r/1-import_pipeline/12-transform/12-transform-utils.R"
_RESHAPE = "r/1-import_pipeline/12-transform/12-reshape.R"
_DISCOVERY = "r/1-import_pipeline/10-file_io/10-discovery.R"
_BATCHING = "r/1-import_pipeline/11-reading/11-batching.R"
_PROCESSING = "r/1-import_pipeline/12-transform/12-processing.R"
_VALIDATE = "r/1-import_pipeline/13-output/13-validate.R"
_SORTING = "r/0-general_pipeline/02-helpers/02-sorting.R"
_OUTPUT = "r/1-import_pipeline/13-output/13-output.R"
# Postpro rule engine: match-key encode/decode + strategy config, then the tokenized match /
# concat merge / change count. Both source only constants + normalize_string at runtime.
_MATCHING_STRATEGY = "r/2-postpro_pipeline/23-postpro_rule_engine/23-matching-strategy.R"
_MATCHING_VALUES = "r/2-postpro_pipeline/23-postpro_rule_engine/23-matching-values.R"
_TARGET_APPLY = "r/2-postpro_pipeline/23-postpro_rule_engine/23-target-apply.R"
_STAGE_DEFINITIONS = "r/2-postpro_pipeline/21-postpro_utilities/21-stage-definitions.R"
_SCHEMA_VALIDATION = "r/2-postpro_pipeline/23-postpro_rule_engine/23-schema-validation.R"
_CONDITIONAL_GROUP = "r/2-postpro_pipeline/23-postpro_rule_engine/23-conditional-group.R"
_FOOTNOTE_RULES = "r/2-postpro_pipeline/23-postpro_rule_engine/23-footnote-rules.R"
# Data audit: config defines empty_audit_findings_dt (used by the validators), validation defines
# the validators + master validation. Orchestration is not sourced — parse_double is called
# directly in the preamble to capture the parser-vs-regex divergence.
_AUDIT_CONFIG = "r/2-postpro_pipeline/20-data_audit/20-audit-config.R"
_AUDIT_VALIDATION = "r/2-postpro_pipeline/20-data_audit/20-audit-validation.R"
# Postpro utilities: diagnostics (build_layer_diagnostics) + template rules (read_rule_table with
# the sheet schema-matching heuristic; needs get_canonical_rule_columns from stage-definitions).
_AUDIT_DIAGNOSTICS = "r/2-postpro_pipeline/21-postpro_utilities/21-diagnostics.R"
_TEMPLATE_RULES = "r/2-postpro_pipeline/21-postpro_utilities/21-template-rules.R"
# Multi-pass driver (B6): payload orchestration, runtime-cache payload loading, and the
# clean/harmonize layer runner + controls/cycle detection + stage-input canonicalization.
_DIRECTORIES = "r/0-general_pipeline/01-setup/01-directories.R"
_RUNTIME_CACHE = "r/2-postpro_pipeline/21-postpro_utilities/21-runtime-cache.R"
_PAYLOAD_APPLICATION = "r/2-postpro_pipeline/23-postpro_rule_engine/23-payload-application.R"
_STAGE_INPUTS = "r/2-postpro_pipeline/22-clean_harmonize_data/22-stage-inputs.R"
_CONTROLS_CACHE = "r/2-postpro_pipeline/22-clean_harmonize_data/22-controls-cache.R"
_LAYER_RUNNER = "r/2-postpro_pipeline/22-clean_harmonize_data/22-layer-runner.R"
# Standardize units core (C3): numeric coercion, rule prep, and the affine-conversion engine.
_NUMERIC_COERCION = "r/0-general_pipeline/02-helpers/02-numeric-coercion.R"
_STANDARDIZE_RULES_SETUP = "r/2-postpro_pipeline/24-standardize_units/24-rules-setup.R"
_STANDARDIZE_ENGINE = "r/2-postpro_pipeline/24-standardize_units/24-standardize-engine.R"
_STANDARDIZE_AGGREGATION = "r/2-postpro_pipeline/24-standardize_units/24-standardize-aggregation.R"
_STANDARDIZE_ORCHESTRATION = (
    "r/2-postpro_pipeline/24-standardize_units/24-standardize-orchestration.R"
)
# Postpro diagnostics (C5): clean/harmonize + standardize rule summaries (matched + unmatched).
_RULE_SUMMARIES = "r/2-postpro_pipeline/25-postpro_diagnostics/25-rule-summaries.R"
_STANDARDIZE_SUMMARIES = "r/2-postpro_pipeline/25-postpro_diagnostics/25-standardize-summaries.R"
# Export processed-data: the high-performance TSV writer (data.table::fwrite(sep = "\t")).
_WRITE_PROCESSED_TABLE = "r/3-export_pipeline/30-processed_data/03-write-processed-table-fast.R"
# Export lists: layer detection (30/02) + the four 31-lists scripts (unique values, sheet
# grouping, column resolution, cache).
_COLLECT_LAYERS = "r/3-export_pipeline/30-processed_data/02-collect-layer-tables.R"
_LISTS_01 = "r/3-export_pipeline/31-lists/01-sheet-order-and-infer.R"
_LISTS_02 = "r/3-export_pipeline/31-lists/02-build-path-and-unique-values.R"
_LISTS_03 = "r/3-export_pipeline/31-lists/03-resolve-and-compare.R"
_LISTS_04 = "r/3-export_pipeline/31-lists/04-cache-and-write.R"

# Stage-level (run_import_pipeline) golden: the orchestration body is replicated inline over
# the whole corpus (R's run_import_pipeline auto-sources via here::here + auto-runs, which the
# harness cannot do; the ported logic is the discover -> fused read+transform -> drop_na ->
# validate -> consolidate -> sort sequence). Sys.Date is pinned for deterministic year ranges.
_STAGE_PREAMBLE = (
    "Sys.Date <- function() as.Date('2025-06-15')\n"
    "config <- list("
    "column_required = c('continent','polity','unit','footnotes'), "
    "column_id = c('commodity','variable','unit','hemisphere','continent','polity','footnotes'), "
    "column_order = c('hemisphere','continent','polity','commodity','variable','unit','year',"
    "'value','notes','footnotes','yearbook','document'), "
    "defaults = list(notes_value = NA_character_, unknown_commodity = '(unknown_commodity)'))\n"
    "file_list <- discover_files(file.path(fixtures_dir, 'corpus'))\n"
    "fused <- read_transform_pipeline_files(file_list, config)\n"
    "long <- drop_na_value_rows(fused$transformed$long_raw)\n"
    "vres <- validate_long_dt_by_document(long, config)\n"
    "audited <- if (nrow(vres$data) == 0L) list() else list(vres$data)\n"
    "cons <- consolidate_audited_dt(audited, config)\n"
    "data <- sort_pipeline_stage_dt(cons$data)"
)

# Validate a multi-document long frame. Pin Sys.Date so the plausible-year range in the error
# text is deterministic (current_year 2025 -> max_year 2026); the Python parity test passes the
# same current_year. `values` is the array-of-objects fixture read by fromJSON as a data.frame.
_VALIDATE_PREAMBLE = (
    "Sys.Date <- function() as.Date('2025-06-15')\n"
    "config <- list(column_required = c('continent','polity','unit','footnotes'))\n"
    "res <- validate_long_dt_by_document(values, config)"
)

# Discover the whole corpus, then run the fused read+transform pipeline over all workbooks and
# capture the combined long frame. R's future plan is sequential here (none set), so this is
# the sequential golden that both Python sequential and parallel output must match.
_PROCESSING_PREAMBLE = (
    "config <- list("
    "column_required = c('continent','polity','unit','footnotes'), "
    "column_id = c('commodity','variable','unit','hemisphere','continent','polity','footnotes'), "
    "column_order = c('hemisphere','continent','polity','commodity','variable','unit','year',"
    "'value','notes','footnotes','yearbook','document'), "
    "defaults = list(notes_value = NA_character_))\n"
    "file_list <- discover_files(file.path(fixtures_dir, 'corpus'))\n"
    "long <- read_transform_pipeline_files(file_list, config)$transformed$long_raw"
)

# Read one corpus sheet, then run the full per-file transform (normalize key fields, clean
# year headers, melt wide->long, add document/notes/yearbook, drop null-value rows). The
# exports capture the resulting long frame column-by-column. column_order drives year-column
# identification; defaults$notes_value feeds the notes column (value_column + the drop toggle
# come from the sourced constants, not this config).
_TRANSFORM_PREAMBLE = (
    "config <- list("
    "column_required = c('continent','polity','unit','footnotes'), "
    "column_id = c('commodity','variable','unit','hemisphere','continent','polity','footnotes'), "
    "column_order = c('hemisphere','continent','polity','commodity','variable','unit','year',"
    "'value','notes','footnotes','yearbook','document'), "
    "defaults = list(notes_value = NA_character_))\n"
    "wb <- file.path(fixtures_dir, "
    "'corpus/fao_1949/fao_1949_crops/r_fao_1949_crops_92_92_date.xlsx')\n"
    "wide <- read_excel_sheet(wb, 'production', config)$data\n"
    "long <- transform_file_dt(wide, 'r_fao_1949_crops_92_92_date.xlsx', "
    "'fao_1949', 'date', config)$long_raw"
)

# Build a minimal config (column_required + column_id, frozen constants) and read one corpus
# sheet once via readxl; the exports then capture each column of the FILTERED result. The
# corpus workbook is located under the committed fixtures dir so R and Python read the same
# bytes. Single quotes keep it embeddable in the double-quoted bootstrap heredoc.
_SHEET_READ_PREAMBLE = (
    "config <- list("
    "column_required = c('continent','polity','unit','footnotes'), "
    "column_id = c('commodity','variable','unit','hemisphere','continent','polity','footnotes'))\n"
    "sheet_res <- read_excel_sheet(file.path(fixtures_dir, "
    "'corpus/fao_1949/fao_1949_crops/r_fao_1949_crops_92_92_date.xlsx'), 'production', config)$data"
)

# Canonical set exactly as 11-sheet-read.R builds it: unique(column_required + column_id).
_CANON = "c('continent','polity','unit','footnotes','commodity','variable','hemisphere')"


def _renames_expr(raw: str, part: str, alias_map: str | None = None) -> str:
    """Build an R expression capturing one field of resolve_canonical_header_renames.

    ``raw`` is an ASCII-only R character vector literal (non-ASCII stays in JSON fixtures to
    avoid Windows script-encoding corruption); ``part`` is ``"old"`` or ``"new"``.
    """
    alias_arg = f", alias_map = {alias_map}" if alias_map is not None else ""
    return (
        f"resolve_canonical_header_renames({raw}, normalize_header_names({raw}), "
        f"{_CANON}{alias_arg})${part}"
    )


# R's collision detection, replicated cli-free so the capture needs no cli::format_error.
_VALIDATE_DUPS = (
    "local({ nv <- normalize_header_names(c('A B','A  B','a__b','Foo','foo','A-B')); "
    "nv <- nv[!is.na(nv) & nzchar(nv)]; "
    "unique(nv[duplicated(nv) | duplicated(nv, fromLast = TRUE)]) })"
)

# Duplicate-alias-target scenario: two aliases both map to polity (only the first survives).
_DEDUP_RAW = "c('Country', 'Nation', 'Continent')"
_DEDUP_ALIAS = "c(country = 'polity', nation = 'polity')"

# Rule-engine matching: the `values` fixture is an array-of-objects (fromJSON -> data.frame),
# one parallel vector per function argument. Coerce every column to character so a mostly-null
# column is not simplified to logical. The concatenate delimiter is the constant default ('; ').
_MATCHING_PREAMBLE = (
    "current_values <- as.character(values$current)\n"
    "condition_values <- as.character(values$condition)\n"
    "existing_values <- as.character(values$existing)\n"
    "incoming_values <- as.character(values$incoming)\n"
    "before_values <- as.character(values$before)\n"
    "after_values <- as.character(values$after)\n"
    "target_values <- as.character(values$target)"
)

# target_apply: four scenarios exercising both strategies + the overwrite-event emitter. Each
# builds a fresh data.table dataset (the R function mutates by reference) and update table from
# the fixture, then runs apply_target_updates_with_strategy. Unicode lives in the fixture; the
# preamble stays ASCII. A: last_rule_wins fast path (unique rows) + condition match/no-match +
# literal-wildcard-on-plain-column + transliteration. B: last_rule_wins slow path with a
# conflict (order_columns sort, null candidate -> "NA" paste, same-value row emits no event).
# C: concatenate with a filtered conditioned update. D: wildcard-already-present removal.
_TARGET_APPLY_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "dsA <- data.table::data.table(unit = mk(values$dataset_unit))\n"
    "updA <- data.table::data.table(row_id = mk(values$A_row_id), "
    "value_target_result = mk(values$A_value), value_target_raw = mk(values$A_cond))\n"
    "resA <- apply_target_updates_with_strategy(dsA, updA, 'unit', dataset_name = 'whep', "
    "execution_stage = 'clean', rule_file_identifier = 'rules.xlsx', source_column = 'commodity')\n"
    "dsB <- data.table::data.table(unit = mk(values$dataset_unit))\n"
    "updB <- data.table::data.table(row_id = mk(values$B_row_id), "
    "value_target_result = mk(values$B_value), value_target_raw = mk(values$B_cond), "
    "seq = mk(values$B_seq))\n"
    "resB <- apply_target_updates_with_strategy(dsB, updB, 'unit', order_columns = 'seq', "
    "dataset_name = 'whep', execution_stage = 'clean', rule_file_identifier = 'rules.xlsx', "
    "source_column = 'commodity')\n"
    "dsC <- data.table::data.table(notes = mk(values$dataset_notes))\n"
    "updC <- data.table::data.table(row_id = mk(values$C_row_id), "
    "value_target_result = mk(values$C_value), value_target_raw = mk(values$C_cond))\n"
    "resC <- apply_target_updates_with_strategy(dsC, updC, 'notes', dataset_name = 'whep', "
    "execution_stage = 'clean', rule_file_identifier = 'rules.xlsx', source_column = 'commodity')\n"
    "dsD <- data.table::data.table(notes = mk(values$dataset_notes_d))\n"
    "updD <- data.table::data.table(row_id = mk(values$D_row_id), "
    "value_target_result = mk(values$D_value), value_target_raw = mk(values$D_cond))\n"
    "resD <- apply_target_updates_with_strategy(dsD, updD, 'notes', dataset_name = 'whep', "
    "execution_stage = 'harmonize', rule_file_identifier = 'rulesD.xlsx', source_column = 'polity')"
)

# schema_validation: dictionary grouping/ordering (radix code-point + NA-last, over a unicode/
# case/NA rule set) via the flattened groups; coerce_rule_schema (prefix strip + canonical
# reorder + value_source optional/synthesized + source_value_column_present); and abort-or-not
# for validate_canonical_rules (valid / duplicate-key / missing-dataset-column), captured with
# try() since cli_abort would otherwise crash the Rscript. Unicode lives in the fixture; the
# preamble stays ASCII.
_SCHEMA_VALIDATION_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "mkrules <- function(cs, vsr, vs, ct, vtr, vt) data.table::data.table("
    "column_source = mk(cs), value_source_raw = mk(vsr), value_source = mk(vs), "
    "column_target = mk(ct), value_target_raw = mk(vtr), value_target = mk(vt))\n"
    "dict_rules <- mkrules(values$dict_cs, values$dict_vsr, values$dict_vs, values$dict_ct, "
    "values$dict_vtr, values$dict_vt)\n"
    "dict <- build_conditional_rule_dictionary(dict_rules, 'clean')\n"
    "dict_flat <- data.table::rbindlist(dict)\n"
    "coercedA <- coerce_rule_schema(data.table::data.table("
    "clean_value_target = mk(values$cA_vt), clean_column_source = mk(values$cA_cs), "
    "clean_value_target_raw = mk(values$cA_vtr), clean_value_source = mk(values$cA_vs), "
    "clean_column_target = mk(values$cA_ct), clean_value_source_raw = mk(values$cA_vsr)), "
    "'clean', 'rulesA.xlsx')\n"
    "coercedB <- coerce_rule_schema(data.table::data.table("
    "clean_column_source = mk(values$cB_cs), clean_value_source_raw = mk(values$cB_vsr), "
    "clean_column_target = mk(values$cB_ct), clean_value_target_raw = mk(values$cB_vtr), "
    "clean_value_target = mk(values$cB_vt)), 'clean', 'rulesB.xlsx')\n"
    "dataset <- data.table::data.table(commodity = mk(values$ds_commodity), "
    "unit = mk(values$ds_unit), continent = mk(values$ds_continent))\n"
    "v_rules <- mkrules(values$v_cs, values$v_vsr, values$v_vs, values$v_ct, values$v_vtr, "
    "values$v_vt)\n"
    "dup_rules <- mkrules(values$dup_cs, values$dup_vsr, values$dup_vs, values$dup_ct, "
    "values$dup_vtr, values$dup_vt)\n"
    "mc_rules <- mkrules(values$mc_cs, values$mc_vsr, values$mc_vs, values$mc_ct, values$mc_vtr, "
    "values$mc_vt)\n"
    "aborts <- function(r) as.character(inherits(try(validate_canonical_rules("
    "r, dataset, 'rules.xlsx', 'clean'), silent = TRUE), 'try-error'))"
)

# conditional_group: four scenarios for apply_conditional_rule_group. Each builds a fresh
# data.table dataset (mutated by reference) and a coerced-form rule group (with the
# source_value_column_present flag), then runs the function. M: two rules over four rows incl. a
# transliteration match ("Café" via "cafe"), exercising audit grouping + affected-row counts +
# (source, target) both changing. SO: a source rewrite whose target update is a no-op — must mark
# only the source column. TO: no source-result value (flag FALSE) — target-only. NM: no match.
# Unicode lives in the fixture; the preamble stays ASCII.
_CONDITIONAL_GROUP_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "mkgroup <- function(cs, vsr, vs, ct, vtr, vt, svc) data.table::data.table("
    "column_source = mk(cs), value_source_raw = mk(vsr), value_source = mk(vs), "
    "column_target = mk(ct), value_target_raw = mk(vtr), value_target = mk(vt), "
    "source_value_column_present = as.logical(mk(svc)))\n"
    "run <- function(ds, g) apply_conditional_rule_group(ds, group_rules = g, "
    "stage_name = 'clean', dataset_name = 'whep', rule_file_id = 'rules.xlsx', "
    "execution_timestamp_utc = '2026-01-01T00:00:00Z')\n"
    "dsM <- data.table::data.table(commodity = mk(values$M_ds_commodity), "
    "unit = mk(values$M_ds_unit))\n"
    "resM <- run(dsM, mkgroup(values$M_r_cs, values$M_r_vsr, values$M_r_vs, values$M_r_ct, "
    "values$M_r_vtr, values$M_r_vt, values$M_r_svc))\n"
    "dsS <- data.table::data.table(commodity = mk(values$SO_ds_commodity), "
    "unit = mk(values$SO_ds_unit))\n"
    "resS <- run(dsS, mkgroup(values$SO_r_cs, values$SO_r_vsr, values$SO_r_vs, values$SO_r_ct, "
    "values$SO_r_vtr, values$SO_r_vt, values$SO_r_svc))\n"
    "dsT <- data.table::data.table(commodity = mk(values$TO_ds_commodity), "
    "unit = mk(values$TO_ds_unit))\n"
    "resT <- run(dsT, mkgroup(values$TO_r_cs, values$TO_r_vsr, values$TO_r_vs, values$TO_r_ct, "
    "values$TO_r_vtr, values$TO_r_vt, values$TO_r_svc))\n"
    "dsN <- data.table::data.table(commodity = mk(values$NM_ds_commodity), "
    "unit = mk(values$NM_ds_unit))\n"
    "resN <- run(dsN, mkgroup(values$NM_r_cs, values$NM_r_vsr, values$NM_r_vs, values$NM_r_ct, "
    "values$NM_r_vtr, values$NM_r_vt, values$NM_r_svc))"
)

# footnote_rules: one rich dataset + rule set exercising replace / remove / multi-token /
# precedence (remove>replace, first-replacement) / NA / "" / trailing-";" / whitespace /
# conditional-target / transliteration / no-op, applied at once. apply_footnote_rules mutates
# the dataset in place; res$data is the mutated frame. Unicode lives in the fixture.
_FOOTNOTE_RULES_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "ds <- data.table::data.table(footnotes = mk(values$ds_footnotes), unit = mk(values$ds_unit))\n"
    "rules <- data.table::data.table(column_source = mk(values$r_cs), "
    "value_source_raw = mk(values$r_vsr), value_source = mk(values$r_vs), "
    "column_target = mk(values$r_ct), value_target_raw = mk(values$r_vtr), "
    "value_target = mk(values$r_vt))\n"
    "res <- apply_footnote_rules(ds, rules, 'clean', 'whep', 'rules.xlsx', '2026-01-01T00:00:00Z')"
)

# data_audit: build a dataset from the fixture (value + document columns), run master validation
# with an explicit audit map (character_non_empty on document, numeric_string on value), and parse
# value via readr::parse_double. The fixture packs the parser-vs-regex divergence: "-3.5", "3.",
# ".5", "1e5", "+3" are all FLAGGED by numeric_string yet PARSE fine; "bad"/""/"1,000" parse to NA.
_DATA_AUDIT_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "dataset <- data.table::data.table(value = mk(values$value), document = mk(values$document))\n"
    "audit_map <- list(character_non_empty = c('document'), numeric_string = c('value'))\n"
    "mvres <- run_master_validation(dataset, audit_map)\n"
    "findings <- data.table::as.data.table(mvres$findings)\n"
    "parsed <- suppressWarnings(readr::parse_double(as.character(dataset$value)))"
)

# utilities: read_rule_table over the committed xlsx rule fixture (prefix strip + sheet
# schema-matching heuristic + all-as-text: "007"/"1000.0" stay strings), plus
# build_layer_diagnostics for a matched (affected_rows sum > 0) and an empty (warn) audit table.
_UTILITIES_PREAMBLE = (
    "rules <- read_rule_table(file.path(fixtures_dir, 'synthetic/clean_rules_sample.xlsx'))\n"
    "audit_matched <- data.table::data.table(affected_rows = c(2L, 3L))\n"
    "audit_empty <- data.table::data.table(affected_rows = integer(0))\n"
    "diag_matched <- build_layer_diagnostics('clean', 10L, 10L, audit_matched)\n"
    "diag_empty <- build_layer_diagnostics('clean', 5L, 5L, audit_empty)"
)

# read_rule_table CSV branch (DB2): readr::read_csv(col_types = cols(.default = col_character()))
# maps BOTH "" and the literal "NA" to NA (readr default na = c("", "NA")); the leading-zero code
# and the quoted comma survive as exact strings. This is the golden the polars CSV read must match.
_RULE_TABLE_CSV_PREAMBLE = (
    "rules_csv <- read_rule_table(file.path(fixtures_dir, 'synthetic/rule_table_sample.csv'))"
)

# layer_batch (B6): run the multi-pass clean + harmonize drivers over the committed rule
# workbooks (clean_rules.xlsx / harmonize_rules.xlsx under fixtures rule_files/). The config
# points import dirs at those fixtures and disables the runtime cache (build-each-call). Each
# stage converges in 2 passes (pass 1 rewrites, pass 2 is a no-op -> changed==0).
_LAYER_BATCH_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "config <- list(paths = list(data = list(import = list("
    "cleaning = file.path(fixtures_dir, 'rule_files/clean'), "
    "harmonization = file.path(fixtures_dir, 'rule_files/harmonize')))), "
    "postpro = list(runtime_cache = list(enabled = FALSE)))\n"
    "dataset <- data.table::data.table(commodity = mk(values$commodity), "
    "unit = mk(values$unit), value = mk(values$value))\n"
    "res_clean <- run_rule_stage_layer_batch(dataset, config, 'clean')\n"
    "diag_clean <- attr(res_clean, 'layer_diagnostics'); mp_clean <- diag_clean$multi_pass\n"
    "res_harm <- run_rule_stage_layer_batch(dataset, config, 'harmonize')\n"
    "diag_harm <- attr(res_harm, 'layer_diagnostics'); mp_harm <- diag_harm$multi_pass"
)

# standardize (C3): prepare rules + apply_standardize_rules over one rich scenario — a specific
# prefixed rule (egg "1000 egg" -> revert -> tonne), a kg fallback (wheat), an offset conversion
# (temp celsius->fahrenheit), a comma-thousands prefix fold (cow "1,000 head" -> base head ->
# fallback tonne), and an unmatched row (milk hectoliter). matched_rule_counts sorted for a
# stable compare.
_STANDARDIZE_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "mapped <- data.table::data.table(commodity = mk(values$commodity), "
    "unit = mk(values$unit), value = mk(values$value))\n"
    "raw_rules <- data.table::data.table(commodity_key = mk(values$rule_commodity), "
    "unit_source = mk(values$rule_source), unit_target = mk(values$rule_target), "
    "unit_factor = mk(values$rule_factor), unit_offset = mk(values$rule_offset))\n"
    "prepared <- prepare_standardize_rules(raw_rules)\n"
    "res <- apply_standardize_rules(mapped, prepared, 'unit', 'value', 'commodity')\n"
    "mrc <- data.table::as.data.table(res$matched_rule_counts)[order("
    "rule_commodity_match_key, applied_commodity_match_key, unit_source_key)]"
)

# standardize_agg (C4): duplicate-group aggregation (sum measure; all-NA group -> NA; unique rows
# kept) + build_standardize_layer_audit (merge prepared rules with matched counts). Both sorted
# for a stable compare.
_STANDARDIZE_AGG_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "agg_in <- data.table::data.table(commodity = mk(values$agg_commodity), "
    "unit = mk(values$agg_unit), value = as.numeric(values$agg_value))\n"
    "agg <- data.table::as.data.table(aggregate_standardized_rows(agg_in, 'value'))"
    "[order(commodity, unit)]\n"
    "layer_rules <- prepare_standardize_rules(data.table::data.table("
    "commodity_key = mk(values$r_commodity), unit_source = mk(values$r_source), "
    "unit_target = mk(values$r_target), unit_factor = as.numeric(values$r_factor), "
    "unit_offset = as.numeric(values$r_offset), source_rule_sheet = mk(values$r_sheet), "
    "source_rule_file = mk(values$r_file)))\n"
    "mrc <- data.table::data.table(rule_commodity_match_key = mk(values$m_rule), "
    "applied_commodity_match_key = mk(values$m_applied), unit_source_key = mk(values$m_unitkey), "
    "affected_rows = as.integer(values$m_affected), source_unit_raw = mk(values$m_raw), "
    "detected_prefix = as.numeric(values$m_prefix), "
    "unit_factor_effective = as.numeric(values$m_eff))\n"
    "audit <- data.table::as.data.table(build_standardize_layer_audit("
    "layer_rules, mrc, values$r_file[[1]]))[order(commodity_key)]"
)

# diagnostics (C5): clean matched summary (value_source/target from *_result) + unmatched
# (anti-join), and standardize matched summary + unmatched via the normalized-key counts branch
# (an all-commodity rule matched by counts leaves the specific wheat/tonne rule unmatched).
_DIAGNOSTICS_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "clean_audit <- data.table::data.table(loop = as.integer(values$ca_loop), "
    "rule_file_identifier = mk(values$ca_rf), column_source = mk(values$ca_cs), "
    "value_source_raw = mk(values$ca_vsr), value_source_result = mk(values$ca_vsres), "
    "column_target = mk(values$ca_ct), value_target_raw = mk(values$ca_vtr), "
    "value_target_result = mk(values$ca_vtres), affected_rows = as.integer(values$ca_aff))\n"
    "cs <- summarize_stage_rules(clean_audit, 'clean')\n"
    "clean_catalog <- data.table::data.table(rule_file_identifier = mk(values$cc_rf), "
    "column_source = mk(values$cc_cs), value_source_raw = mk(values$cc_vsr), "
    "value_source = mk(values$cc_vs), column_target = mk(values$cc_ct), "
    "value_target_raw = mk(values$cc_vtr), value_target = mk(values$cc_vt))\n"
    "cu <- build_unmatched_rule_summary(clean_catalog, cs)\n"
    "std_audit <- data.table::data.table(rule_file_identifier = mk(values$sa_rf), "
    "commodity_key = mk(values$sa_commodity), unit_source = mk(values$sa_source), "
    "unit_target = mk(values$sa_target), unit_factor = as.numeric(values$sa_factor), "
    "unit_offset = as.numeric(values$sa_offset), affected_rows = as.integer(values$sa_aff))\n"
    "ss <- summarize_standardize_rules(std_audit)\n"
    "std_catalog <- data.table::data.table(rule_file_identifier = mk(values$sc_rf), "
    "commodity_key = mk(values$sc_commodity), unit_source = mk(values$sc_source), "
    "unit_target = mk(values$sc_target), unit_factor = as.numeric(values$sc_factor), "
    "unit_offset = as.numeric(values$sc_offset))\n"
    "std_counts <- data.table::data.table(rule_commodity_match_key = mk(values$sm_rule), "
    "unit_source_key = mk(values$sm_unitkey))\n"
    "su <- build_unmatched_standardize_rule_summary(std_catalog, ss, std_counts)"
)

# export_processed_data: build a harmonize-layer export frame from the fixture (all columns
# character except `value`, which the audit stage parses to double via readr::parse_double ->
# as.numeric here), then write it with the real `write_processed_table_fast` (fwrite, sep="\t").
# The whole TSV is captured as a hex string so the golden is the exact bytes: it pins the eol
# (fwrite uses the platform newline), the auto-quoting (tab/newline/quote/empty-vs-NA), and the
# double formatting (15 sig figs, fixed notation, `.0` dropped — this bootstrap runs under
# scipen=999, like the pipeline). The Python writer must reproduce these bytes exactly.
_EXPORT_PROCESSED_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "dt <- data.table::data.table("
    "hemisphere = mk(values$hemisphere), continent = mk(values$continent), "
    "polity = mk(values$polity), commodity = mk(values$commodity), "
    "variable = mk(values$variable), unit = mk(values$unit), year = mk(values$year), "
    "value = as.numeric(values$value), notes = mk(values$notes), "
    "footnotes = mk(values$footnotes), yearbook = mk(values$yearbook), "
    "document = mk(values$document))\n"
    "tmp <- tempfile(fileext = '.tsv')\n"
    "write_processed_table_fast(dt, tmp)\n"
    "raw_bytes <- readBin(tmp, what = 'raw', n = file.info(tmp)$size)\n"
    "unlink(tmp)\n"
    "tsv_hex <- paste(sprintf('%02x', as.integer(raw_bytes)), collapse = '')"
)

# export_lists: build the four layer objects from the fixture, then run the real 31-lists logic
# (collect -> by-sheet -> union -> resolve columns -> unique cache -> per-column sheet grouping).
# The golden is captured as atomic vectors: per-(layer, column) unique values (drop-null +
# code-point/radix sort + "(blank)" prepend — parity risk #7 on the unnitialized raw layer), the
# union + resolved export columns, and per-column merged sheet names (the identical-layer grouping
# and fixed order). The polars port must reproduce all of them.
_EXPORT_LISTS_COLUMNS = ("continent", "polity", "commodity", "unit")
_EXPORT_LISTS_EXPORTS: dict[str, str] = {
    "union_columns": "union_columns",
    "export_columns": "export_columns",
    **{
        f"uniq_{layer}_{column}": f"unique_cache[['{layer}']][['{column}']]"
        for layer in ("raw", "clean", "normalize", "harmonize")
        for column in _EXPORT_LISTS_COLUMNS
    },
    **{f"sheets_{column}": f"sheet_names_for('{column}')" for column in _EXPORT_LISTS_COLUMNS},
}
_EXPORT_LISTS_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "build_layer <- function(L) data.table::data.table("
    "continent = mk(values[[L]]$continent), polity = mk(values[[L]]$polity), "
    "commodity = mk(values[[L]]$commodity), unit = mk(values[[L]]$unit), "
    "year = mk(values[[L]]$year), value = mk(values[[L]]$value))\n"
    "objs <- list(whep_data_raw = build_layer('raw'), whep_data_clean = build_layer('clean'), "
    "whep_data_normalize = build_layer('normalize'), "
    "whep_data_harmonize = build_layer('harmonize'))\n"
    "config <- list(export_config = list(lists_to_export = "
    "c('continent','polity','commodity','unit','footnotes')))\n"
    "layer_tables <- collect_layer_tables_for_export(data_objects = objs, "
    "env = new.env(parent = emptyenv()))\n"
    "layer_by_sheet <- build_layer_tables_by_sheet(layer_tables)\n"
    "union_columns <- collect_union_columns(layer_by_sheet)\n"
    "export_columns <- resolve_lists_export_columns(config, union_columns)\n"
    "unique_cache <- build_column_unique_cache(layer_by_sheet, export_columns)\n"
    "sheet_names_for <- function(col) {\n"
    "  dts <- lapply(get_lists_sheet_order(), function(L) {\n"
    "    v <- unique_cache[[L]][[col]]; if (is.null(v)) v <- character(0)\n"
    "    data.table::data.table(value = v)\n"
    "  })\n"
    "  names(resolve_list_sheet_payloads(dts[[1]], dts[[2]], dts[[3]], dts[[4]]))\n"
    "}"
)

# postpro_stage: the full run_postpro_pipeline_batch DATA path over the frozen import output
# (postpro_stage_input.json is the verified import_stage frame; import parity guarantees it equals
# R's byte-for-byte, so it is a legitimate frozen input for both sides). Replicates the nine-step
# orchestration's data effects — the audit value-parse (readr::parse_double, invalid rows retained),
# then clean -> standardize -> harmonize, each canonically sorted before feeding the next. Rule dirs
# point at committed postpro-stage fixtures (clean_ rewrites milk's unit; harmonize_ rewrites date's
# unit, keyed on the POST-standardize value — proving harmonize runs on the normalized frame).
# There are no standardize rules, yet the engine still folds numeric unit prefixes into value.
# Diagnostics are read from the UNSORTED layer result (attribute-independent of the sort). Both
# clean and harmonize converge in two passes. The Python run_postpro_pipeline must match all of it.
_POSTPRO_STAGE_LAYERS = (
    ("clean", "clean_dt"),
    ("normalize", "normalize_dt"),
    ("harmonize", "harmonize_dt"),
)
_POSTPRO_STAGE_COLUMNS = (
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "value",
    "notes",
    "footnotes",
    "yearbook",
    "document",
)
_POSTPRO_STAGE_EXPORTS: dict[str, str] = {
    **{f"{layer}_columns": f"colnames({var})" for layer, var in _POSTPRO_STAGE_LAYERS},
    **{f"{layer}_nrow": f"as.character(nrow({var}))" for layer, var in _POSTPRO_STAGE_LAYERS},
    **{
        f"{layer}_{column}": f"{var}[['{column}']]"
        for layer, var in _POSTPRO_STAGE_LAYERS
        for column in _POSTPRO_STAGE_COLUMNS
    },
    "clean_stop_reason": "clean_mp$stop_reason",
    "clean_passes": "as.character(clean_mp$passes_executed)",
    "clean_converged": "as.character(clean_mp$converged)",
    "clean_matched": "as.character(clean_diag$matched_count)",
    "harmonize_stop_reason": "harm_mp$stop_reason",
    "harmonize_passes": "as.character(harm_mp$passes_executed)",
    "harmonize_converged": "as.character(harm_mp$converged)",
    "harmonize_matched": "as.character(harm_diag$matched_count)",
}
_POSTPRO_STAGE_PREAMBLE = (
    "mk <- function(x) as.character(x)\n"
    "raw <- data.table::data.table(\n"
    "  hemisphere = mk(values$hemisphere), continent = mk(values$continent),\n"
    "  polity = mk(values$polity), commodity = mk(values$commodity),\n"
    "  variable = mk(values$variable), unit = mk(values$unit), year = mk(values$year),\n"
    "  value = mk(values$value), notes = mk(values$notes), footnotes = mk(values$footnotes),\n"
    "  yearbook = mk(values$yearbook), document = mk(values$document))\n"
    "audited <- data.table::copy(raw)\n"
    "audited[, value := suppressWarnings(readr::parse_double(as.character(value)))]\n"
    "tmp_root <- tempfile('whep_pp_stage_')\n"
    "dir.create(tmp_root, recursive = TRUE, showWarnings = FALSE)\n"
    "config <- list(paths = list(data = list(\n"
    "  import = list(\n"
    "    cleaning = file.path(fixtures_dir, 'rule_files_postpro/clean'),\n"
    "    harmonization = file.path(fixtures_dir, 'rule_files_postpro/harmonize'),\n"
    "    standardization = file.path(tmp_root, 'standardization')),\n"
    "  audit = list(templates_dir = file.path(tmp_root, 'templates')))),\n"
    "  postpro = list(runtime_cache = list(enabled = FALSE)))\n"
    "clean_res <- run_cleaning_layer_batch(audited, config, dataset_name = 'whep_data_raw')\n"
    "clean_diag <- attr(clean_res, 'layer_diagnostics'); clean_mp <- clean_diag$multi_pass\n"
    "clean_dt <- sort_pipeline_stage_dt(clean_res)\n"
    "normalize_dt <- sort_pipeline_stage_dt(run_standardize_units_layer_batch(clean_dt, config))\n"
    "harm_res <- run_harmonize_layer_batch(normalize_dt, config, dataset_name = 'whep_data_raw')\n"
    "harm_diag <- attr(harm_res, 'layer_diagnostics'); harm_mp <- harm_diag$multi_pass\n"
    "harmonize_dt <- sort_pipeline_stage_dt(harm_res)"
)

CAPTURES: dict[str, CaptureSpec] = {
    # NOTE: string_normalization has no R-parity spec. The normalization POLICY (NFD diacritic
    # strip + non-alnum->space) deliberately diverges from R's ICU Latin-ASCII on symbols /
    # ligatures / non-decomposable letters, so it is verified by policy tests in
    # tests/setup/test_helpers.py, not against an R golden.
    "file_metadata": CaptureSpec(
        module="file_metadata",
        r_sources=(_GENERAL_CONSTANTS, _ASSERTIONS, _FILE_METADATA),
        fixture="synthetic/file_metadata_inputs.json",
        exports={
            "file_path": "extract_file_metadata(values)$file_path",
            "file_name": "extract_file_metadata(values)$file_name",
            "commodity": "extract_file_metadata(values)$commodity",
            "yearbook": "extract_file_metadata(values)$yearbook",
            "is_ascii": "extract_file_metadata(values)$is_ascii",
            "error_message": "extract_file_metadata(values)$error_message",
        },
        description=(
            "Positional file-name token parsing (yearbook = token 2 + first 4-digit token; "
            "commodity = tokens 7+) + ASCII check over real WHEP corpus names and edge cases "
            "(no year token, <2 tokens, first-year-wins, non-ASCII)."
        ),
    ),
    "header_normalization": CaptureSpec(
        module="header_normalization",
        r_sources=(_GENERAL_CONSTANTS, _ASSERTIONS, _HEADER_NORMALIZATION),
        fixture="synthetic/header_names_inputs.json",
        exports={
            "normalize": "normalize_header_names(values)",
            # Canonical match + has_exact guard (commodity present verbatim) + alias fires.
            "renames_main_old": _renames_expr("c(' Continent ', 'Country', 'commodity')", "old"),
            "renames_main_new": _renames_expr("c(' Continent ', 'Country', 'commodity')", "new"),
            # Alias target-present guard: 'polity' already a header -> country not renamed.
            "renames_guarded_old": _renames_expr("c('Country', 'polity')", "old"),
            "renames_guarded_new": _renames_expr("c('Country', 'polity')", "new"),
            # Duplicate-alias-target guard: two aliases -> polity, only the first survives.
            "renames_dedup_old": _renames_expr(_DEDUP_RAW, "old", _DEDUP_ALIAS),
            "renames_dedup_new": _renames_expr(_DEDUP_RAW, "new", _DEDUP_ALIAS),
            # Collision detection (which normalized keys collide), replicated cli-free.
            "validate_dups": _VALIDATE_DUPS,
        },
        description=(
            "Header normalization: the ordered regex chain + Latin-ASCII;Lower transliteration "
            "(top parity risk: anyascii vs ICU on accented/unicode headers), canonical + "
            "country->polity alias renames with all collision guards, and collision detection."
        ),
    ),
    "sheet_read": CaptureSpec(
        module="sheet_read",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _DATA_TABLE,
            _HEADER_NORMALIZATION,
            _READ_UTILS,
            _SHEET_READ,
        ),
        preamble=_SHEET_READ_PREAMBLE,
        exports={
            "columns": "colnames(sheet_res)",
            "nrow": "as.character(nrow(sheet_res))",
            "hemisphere": "sheet_res[['hemisphere']]",
            "continent": "sheet_res[['continent']]",
            "polity": "sheet_res[['polity']]",
            "unit": "sheet_res[['unit']]",
            "footnotes": "sheet_res[['footnotes']]",
            "variable": "sheet_res[['variable']]",
            "y1934_1938": "sheet_res[['1934-1938']]",
            "y1946": "sheet_res[['1946']]",
            "y1947": "sheet_res[['1947']]",
            "y1948": "sheet_res[['1948']]",
        },
        description=(
            "read_excel_sheet over a real corpus workbook (readxl text read): header rename "
            "(country->polity), base-column non-empty row filter, and variable:=sheet name. "
            "Confirms readxl-vs-calamine text extraction matches after filtering."
        ),
    ),
    "transform": CaptureSpec(
        module="transform",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _DATA_TABLE,
            _STRING_NORMALIZATION,
            _DATA_CLEANING,
            _HEADER_NORMALIZATION,
            _READ_UTILS,
            _SHEET_READ,
            _TRANSFORM_UTILS,
            _RESHAPE,
        ),
        preamble=_TRANSFORM_PREAMBLE,
        exports={
            "long_columns": "colnames(long)",
            "long_nrow": "as.character(nrow(long))",
            "commodity": "long[['commodity']]",
            "variable": "long[['variable']]",
            "unit": "long[['unit']]",
            "hemisphere": "long[['hemisphere']]",
            "continent": "long[['continent']]",
            "polity": "long[['polity']]",
            "footnotes": "long[['footnotes']]",
            "year": "long[['year']]",
            "value": "long[['value']]",
            "document": "long[['document']]",
            "notes": "long[['notes']]",
            "yearbook": "long[['yearbook']]",
        },
        description=(
            "Full per-file transform (transform_file_dt) over a real corpus sheet: key-field "
            "normalization, year-header cleanup, wide->long melt (melt -> unpivot, dropping the "
            "same columns), metadata enrichment, and null-value drop. Parity on the long shape."
        ),
    ),
    "processing": CaptureSpec(
        module="processing",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _DATA_TABLE,
            _STRING_NORMALIZATION,
            _DATA_CLEANING,
            _FILE_METADATA,
            _DISCOVERY,
            _HEADER_NORMALIZATION,
            _READ_UTILS,
            _SHEET_READ,
            _BATCHING,
            _TRANSFORM_UTILS,
            _RESHAPE,
            _PROCESSING,
        ),
        preamble=_PROCESSING_PREAMBLE,
        exports={
            "long_columns": "colnames(long)",
            "long_nrow": "as.character(nrow(long))",
            "commodity": "long[['commodity']]",
            "variable": "long[['variable']]",
            "unit": "long[['unit']]",
            "hemisphere": "long[['hemisphere']]",
            "continent": "long[['continent']]",
            "polity": "long[['polity']]",
            "footnotes": "long[['footnotes']]",
            "year": "long[['year']]",
            "value": "long[['value']]",
            "document": "long[['document']]",
            "notes": "long[['notes']]",
            "yearbook": "long[['yearbook']]",
        },
        description=(
            "Fused read+transform (read_transform_pipeline_files) over the whole corpus: the "
            "combined long frame from discovering, batch-reading, and transforming every "
            "workbook. Python sequential AND parallel output must match this byte-for-byte."
        ),
    ),
    "validate": CaptureSpec(
        module="validate",
        r_sources=(_GENERAL_CONSTANTS, _ASSERTIONS, _DATA_TABLE, _VALIDATE),
        fixture="synthetic/validate_long_inputs.json",
        preamble=_VALIDATE_PREAMBLE,
        exports={
            "errors": "res$errors",
            "data_document": "res$data$document",
            "data_value": "res$data$value",
        },
        description=(
            "validate_long_dt_by_document over an interleaved multi-document long frame: verbatim "
            "error strings in the exact 4-key sort order (mandatory / year / duplicate), plus the "
            "document-major reordered data. Covers null + empty missing values, plain/range/"
            "inverted year errors, and a duplicate with a null key value."
        ),
    ),
    "import_stage": CaptureSpec(
        module="import_stage",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _DATA_TABLE,
            _STRING_NORMALIZATION,
            _DATA_CLEANING,
            _SORTING,
            _FILE_METADATA,
            _DISCOVERY,
            _HEADER_NORMALIZATION,
            _READ_UTILS,
            _SHEET_READ,
            _BATCHING,
            _TRANSFORM_UTILS,
            _RESHAPE,
            _PROCESSING,
            _VALIDATE,
            _OUTPUT,
        ),
        preamble=_STAGE_PREAMBLE,
        exports={
            "data_columns": "colnames(data)",
            "data_nrow": "as.character(nrow(data))",
            "hemisphere": "data[['hemisphere']]",
            "continent": "data[['continent']]",
            "polity": "data[['polity']]",
            "commodity": "data[['commodity']]",
            "variable": "data[['variable']]",
            "unit": "data[['unit']]",
            "year": "data[['year']]",
            "value": "data[['value']]",
            "notes": "data[['notes']]",
            "footnotes": "data[['footnotes']]",
            "yearbook": "data[['yearbook']]",
            "document": "data[['document']]",
            "reading_errors": "fused$errors",
            "validation_errors": "vres$errors",
            "warnings": "cons$warnings",
        },
        description=(
            "Stage-level run_import_pipeline over the whole corpus (orchestration replicated "
            "inline): the consolidated, canonically-sorted long frame plus the reading / "
            "validation / consolidation diagnostics. Python run_import_pipeline must match."
        ),
    ),
    "matching": CaptureSpec(
        module="matching",
        r_sources=(_GENERAL_CONSTANTS, _STRING_NORMALIZATION, _MATCHING_STRATEGY, _MATCHING_VALUES),
        fixture="synthetic/matching_values_inputs.json",
        preamble=_MATCHING_PREAMBLE,
        exports={
            # Tokenized ;-membership match (incl. wildcard __ANY__ + NA<->NA) and the plain
            # full-string match over the same current/condition pairs.
            "match_tokenized": (
                "match_rule_target_condition_values("
                "current_values, condition_values, tokenized_target = TRUE)"
            ),
            "match_plain": (
                "match_rule_target_condition_values("
                "current_values, condition_values, tokenized_target = FALSE)"
            ),
            # Match-key encoding: normalized (NA -> na_match_key) and raw (apply_normalization
            # = FALSE) forms.
            "encode_key": "encode_rule_match_key(current_values)",
            "encode_key_raw": "encode_rule_match_key(target_values, apply_normalization = FALSE)",
            # Target NA <-> placeholder round trip (na_placeholder), and the standalone encode.
            "encode_target": "encode_target_rule_value(target_values)",
            "decode_target": "decode_target_rule_value(encode_target_rule_value(target_values))",
            # Order-preserving, existing-first deduplicating concat merge.
            "concat_merge": (
                "concatenate_existing_and_incoming_values(existing_values, incoming_values, '; ')"
            ),
            # Element-wise change count (drives multi-pass convergence).
            "change_count": "count_elementwise_value_changes(before_values, after_values)",
        },
        description=(
            "Rule-engine matching & value merge (23-matching-strategy.R + 23-matching-values.R): "
            "tokenized ;-membership matching with wildcard __ANY__, NA<->NA folding to "
            "na_match_key (parity risk #5), na_placeholder target encode/decode, order-preserving "
            "existing-first concat dedupe, and the element-wise change count — over unicode / NA / "
            "empty / wildcard / duplicate edge cases."
        ),
    ),
    "target_apply": CaptureSpec(
        module="target_apply",
        r_sources=(
            _GENERAL_CONSTANTS,
            _STRING_NORMALIZATION,
            _MATCHING_STRATEGY,
            _MATCHING_VALUES,
            _TARGET_APPLY,
        ),
        fixture="synthetic/target_apply_inputs.json",
        preamble=_TARGET_APPLY_PREAMBLE,
        exports={
            "A_unit": "dsA$unit",
            "A_applied": "resA$applied",
            "A_changed": "resA$changed_value_count",
            "A_ev_nrow": "as.character(nrow(resA$overwrite_events))",
            "B_unit": "dsB$unit",
            "B_applied": "resB$applied",
            "B_changed": "resB$changed_value_count",
            "B_ev_nrow": "as.character(nrow(resB$overwrite_events))",
            "B_ev_row_id": "resB$overwrite_events$row_id",
            "B_ev_candidate_count": "resB$overwrite_events$candidate_count",
            "B_ev_unique_candidate_count": "resB$overwrite_events$unique_candidate_count",
            "B_ev_selected_value": "resB$overwrite_events$selected_value",
            "B_ev_candidate_values": "resB$overwrite_events$candidate_values",
            "B_ev_column_source": "resB$overwrite_events$column_source",
            "B_ev_column_target": "resB$overwrite_events$column_target",
            "B_ev_dataset_name": "resB$overwrite_events$dataset_name",
            "B_ev_execution_stage": "resB$overwrite_events$execution_stage",
            "B_ev_rule_file_identifier": "resB$overwrite_events$rule_file_identifier",
            "C_notes": "dsC$notes",
            "C_applied": "resC$applied",
            "C_changed": "resC$changed_value_count",
            "C_ev_nrow": "as.character(nrow(resC$overwrite_events))",
            "D_notes": "dsD$notes",
            "D_applied": "resD$applied",
            "D_changed": "resD$changed_value_count",
            "D_ev_nrow": "as.character(nrow(resD$overwrite_events))",
        },
        description=(
            "apply_target_updates_with_strategy (23-target-apply.R): last_rule_wins fast path "
            "(unique rows) + condition match and slow path (stable order-column sort, group-last, "
            "overwrite events only when unique_candidate_count>1, null candidate -> 'NA' paste), "
            "plus concatenate and wildcard-already-present removal. Functional scatter must match "
            "R's in-place data.table::set on the mutated column, events table, and change counts."
        ),
    ),
    "schema_validation": CaptureSpec(
        module="schema_validation",
        r_sources=(_GENERAL_CONSTANTS, _STAGE_DEFINITIONS, _SCHEMA_VALIDATION),
        fixture="synthetic/schema_validation_inputs.json",
        preamble=_SCHEMA_VALIDATION_PREAMBLE,
        exports={
            # Dictionary: group count + flattened groups (encodes group order AND within-group
            # radix/code-point order incl. NA-last).
            "dict_ngroups": "as.character(length(dict))",
            "dict_flat_column_source": "dict_flat$column_source",
            "dict_flat_column_target": "dict_flat$column_target",
            "dict_flat_value_source_raw": "dict_flat$value_source_raw",
            "dict_flat_value_target": "dict_flat$value_target",
            # coerce: canonical column set/order, the source_value_column_present flag, and the
            # (synthesized-when-absent) value_source column.
            "cA_columns": "colnames(coercedA)",
            "cA_source_value_column_present": "coercedA$source_value_column_present",
            "cA_value_source": "coercedA$value_source",
            "cA_column_source": "coercedA$column_source",
            "cB_columns": "colnames(coercedB)",
            "cB_source_value_column_present": "coercedB$source_value_column_present",
            "cB_value_source": "coercedB$value_source",
            # validate_canonical_rules abort-or-not (valid / duplicate-key / missing dataset col).
            "validate_valid_aborts": "aborts(v_rules)",
            "validate_duplicate_aborts": "aborts(dup_rules)",
            "validate_missing_column_aborts": "aborts(mc_rules)",
        },
        description=(
            "Rule schema coercion + canonical validation + dictionary construction "
            "(23-schema-validation.R): coerce_rule_schema (stage-prefix strip, canonical reorder, "
            "value_source optional/synthesized, source_value_column_present); "
            "build_conditional_rule_dictionary grouping by (column_source, column_target) with "
            "radix/code-point + NA-last within-group order (parity risk #7); and "
            "validate_canonical_rules duplicate-key / missing-column aborts."
        ),
    ),
    "conditional_group": CaptureSpec(
        module="conditional_group",
        r_sources=(
            _GENERAL_CONSTANTS,
            _STRING_NORMALIZATION,
            _STAGE_DEFINITIONS,
            _MATCHING_STRATEGY,
            _MATCHING_VALUES,
            _TARGET_APPLY,
            _CONDITIONAL_GROUP,
        ),
        fixture="synthetic/conditional_group_inputs.json",
        preamble=_CONDITIONAL_GROUP_PREAMBLE,
        exports={
            "M_commodity": "resM$data$commodity",
            "M_unit": "resM$data$unit",
            "M_changed": "resM$changed_value_count",
            "M_changed_columns": "resM$changed_columns",
            "M_audit_nrow": "as.character(nrow(resM$audit))",
            "M_audit_column_source": "resM$audit$column_source",
            "M_audit_value_source_raw": "resM$audit$value_source_raw",
            "M_audit_value_source_result": "resM$audit$value_source_result",
            "M_audit_column_target": "resM$audit$column_target",
            "M_audit_value_target_raw": "resM$audit$value_target_raw",
            "M_audit_value_target_result": "resM$audit$value_target_result",
            "M_audit_affected_rows": "resM$audit$affected_rows",
            "M_audit_dataset_name": "resM$audit$dataset_name",
            "M_audit_execution_stage": "resM$audit$execution_stage",
            "M_audit_rule_file_identifier": "resM$audit$rule_file_identifier",
            "M_audit_execution_timestamp_utc": "resM$audit$execution_timestamp_utc",
            "SO_commodity": "resS$data$commodity",
            "SO_unit": "resS$data$unit",
            "SO_changed": "resS$changed_value_count",
            "SO_changed_columns": "resS$changed_columns",
            "SO_audit_nrow": "as.character(nrow(resS$audit))",
            "TO_commodity": "resT$data$commodity",
            "TO_unit": "resT$data$unit",
            "TO_changed": "resT$changed_value_count",
            "TO_changed_columns": "resT$changed_columns",
            "TO_audit_nrow": "as.character(nrow(resT$audit))",
            "NM_commodity": "resN$data$commodity",
            "NM_unit": "resN$data$unit",
            "NM_changed": "resN$changed_value_count",
            "NM_changed_columns": "resN$changed_columns",
            "NM_audit_nrow": "as.character(nrow(resN$audit))",
        },
        description=(
            "apply_conditional_rule_group (23-conditional-group.R): cartesian source-key join, "
            "target-condition match on the matched subset, functional source + target scatter, and "
            "the encoded-NA audit join-back. Covers audit grouping/affected-rows + transliteration "
            "match (M), source-only rewrite marking only the source column (SO), target-only (TO), "
            "and no-match (NM). Mutated columns, count, changed_columns, and audit must match."
        ),
    ),
    "footnote_rules": CaptureSpec(
        module="footnote_rules",
        r_sources=(
            _GENERAL_CONSTANTS,
            _STRING_NORMALIZATION,
            _STAGE_DEFINITIONS,
            _MATCHING_STRATEGY,
            _MATCHING_VALUES,
            _TARGET_APPLY,
            _FOOTNOTE_RULES,
        ),
        fixture="synthetic/footnote_rules_inputs.json",
        preamble=_FOOTNOTE_RULES_PREAMBLE,
        exports={
            "footnotes": "res$data$footnotes",
            "unit": "res$data$unit",
            "changed": "res$changed_value_count",
            "changed_columns": "res$changed_columns",
            "overwrite_nrow": "as.character(nrow(res$overwrite_events))",
            "audit_nrow": "as.character(nrow(res$audit))",
            "audit_column_source": "res$audit$column_source",
            "audit_value_source_raw": "res$audit$value_source_raw",
            "audit_value_source_result": "res$audit$value_source_result",
            "audit_column_target": "res$audit$column_target",
            "audit_value_target_raw": "res$audit$value_target_raw",
            "audit_value_target_result": "res$audit$value_target_result",
            "audit_affected_rows": "res$audit$affected_rows",
            "audit_dataset_name": "res$audit$dataset_name",
            "audit_execution_stage": "res$audit$execution_stage",
            "audit_rule_file_identifier": "res$audit$rule_file_identifier",
            "audit_execution_timestamp_utc": "res$audit$execution_timestamp_utc",
        },
        description=(
            "apply_footnote_rules (23-footnote-rules.R): the ;-explode / rule-match / reconstruct "
            "engine. One rich dataset covering replace, remove, multi-token, precedence "
            "(remove>replace, first-replacement), NA/empty/trailing-;/whitespace tokens, "
            "conditional target, transliteration, and no-op. Reconstructed footnotes, mutated "
            "target column, change count, changed_columns, and the full audit table must match R."
        ),
    ),
    "data_audit": CaptureSpec(
        module="data_audit",
        r_sources=(_GENERAL_CONSTANTS, _ASSERTIONS, _AUDIT_CONFIG, _AUDIT_VALIDATION),
        fixture="synthetic/data_audit_inputs.json",
        preamble=_DATA_AUDIT_PREAMBLE,
        exports={
            # Findings table: plan order (character_non_empty on document, then numeric_string on
            # value), 1-based row_index, and the verbatim audit type/message strings.
            "findings_row_index": "findings$row_index",
            "findings_audit_column": "findings$audit_column",
            "findings_audit_type": "findings$audit_type",
            "findings_audit_message": "findings$audit_message",
            "invalid_row_index": "mvres$invalid_row_index",
            # readr::parse_double output (as.character -> "1e+05" etc.); compared numerically.
            "parsed_value": "parsed",
        },
        description=(
            "Data audit (20-audit-validation.R + parse_double): master validation findings "
            "(character_non_empty on document, numeric_string on value) with 1-based row indices "
            "in plan order, the sorted-unique invalid_row_index, and the parsed value column. "
            "Pins parity risk #8 — the audit regex ^[0-9]+(\\.[0-9]+)?$ flags negatives / "
            "scientific / signed values yet parse_double still parses them; invalid rows are "
            "retained in the audited output."
        ),
    ),
    "utilities": CaptureSpec(
        module="utilities",
        r_sources=(_GENERAL_CONSTANTS, _STAGE_DEFINITIONS, _AUDIT_DIAGNOSTICS, _TEMPLATE_RULES),
        preamble=_UTILITIES_PREAMBLE,
        exports={
            # read_rule_table: normalized (prefix-stripped) columns + all-as-text values (the
            # matching clean_rules sheet only; the guidance sheet is skipped by the heuristic).
            "rr_columns": "colnames(rules)",
            "rr_nrow": "as.character(nrow(rules))",
            "rr_column_source": "rules$column_source",
            "rr_value_source_raw": "rules$value_source_raw",
            "rr_value_source": "rules$value_source",
            "rr_column_target": "rules$column_target",
            "rr_value_target_raw": "rules$value_target_raw",
            "rr_value_target": "rules$value_target",
            # build_layer_diagnostics: deterministic fields (the wall-clock timestamp is dropped).
            "diag_matched_matched_count": "as.character(diag_matched$matched_count)",
            "diag_matched_unmatched_count": "as.character(diag_matched$unmatched_count)",
            "diag_matched_status": "diag_matched$status",
            "diag_matched_messages": "diag_matched$messages",
            "diag_empty_matched_count": "as.character(diag_empty$matched_count)",
            "diag_empty_unmatched_count": "as.character(diag_empty$unmatched_count)",
            "diag_empty_status": "diag_empty$status",
            "diag_empty_messages": "diag_empty$messages",
        },
        description=(
            "Postpro utilities (21-template-rules.R + 21-diagnostics.R): read_rule_table over a "
            "committed xlsx rule fixture — clean_/harmonize_ prefix strip, the sheet "
            "schema-matching heuristic (guidance sheet skipped), and all-as-text reads keeping "
            "'007'/'1000.0' as strings; plus build_layer_diagnostics matched/unmatched counts, "
            "status, and message for a matched and an empty audit table."
        ),
    ),
    "rule_table_csv": CaptureSpec(
        module="rule_table_csv",
        r_sources=(_GENERAL_CONSTANTS, _STAGE_DEFINITIONS, _TEMPLATE_RULES),
        preamble=_RULE_TABLE_CSV_PREAMBLE,
        exports={
            "columns": "colnames(rules_csv)",
            "nrow": "as.character(nrow(rules_csv))",
            "column_source": "rules_csv$column_source",
            # Both the empty cell and the literal "NA" must read as NA (JSON null).
            "value_source_raw": "rules_csv$value_source_raw",
            "value_target_raw": "rules_csv$value_target_raw",
        },
        description=(
            "read_rule_table CSV branch (21-template-rules.R, DB2): readr::read_csv with "
            "col_character reads a rule CSV all-as-text; readr's default na = c('', 'NA') maps "
            "both the empty cell and the literal 'NA' to NA, while the leading-zero code '007' and "
            "the quoted field 'a,b' survive verbatim. The polars read must match byte-for-byte."
        ),
    ),
    "layer_batch": CaptureSpec(
        module="layer_batch",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _DIRECTORIES,
            _STRING_NORMALIZATION,
            _STAGE_DEFINITIONS,
            _AUDIT_DIAGNOSTICS,
            _TEMPLATE_RULES,
            _RUNTIME_CACHE,
            _MATCHING_STRATEGY,
            _MATCHING_VALUES,
            _TARGET_APPLY,
            _SCHEMA_VALIDATION,
            _CONDITIONAL_GROUP,
            _FOOTNOTE_RULES,
            _PAYLOAD_APPLICATION,
            _STAGE_INPUTS,
            _CONTROLS_CACHE,
            _LAYER_RUNNER,
        ),
        fixture="synthetic/layer_batch_inputs.json",
        preamble=_LAYER_BATCH_PREAMBLE,
        exports={
            "clean_columns": "colnames(res_clean)",
            "clean_commodity": "res_clean$commodity",
            "clean_unit": "res_clean$unit",
            "clean_value": "res_clean$value",
            "clean_stop_reason": "mp_clean$stop_reason",
            "clean_passes": "as.character(mp_clean$passes_executed)",
            "clean_converged": "as.character(mp_clean$converged)",
            "clean_matched": "as.character(diag_clean$matched_count)",
            "harm_columns": "colnames(res_harm)",
            "harm_commodity": "res_harm$commodity",
            "harm_unit": "res_harm$unit",
            "harm_value": "res_harm$value",
            "harm_stop_reason": "mp_harm$stop_reason",
            "harm_passes": "as.character(mp_harm$passes_executed)",
            "harm_converged": "as.character(mp_harm$converged)",
            "harm_matched": "as.character(diag_harm$matched_count)",
        },
        description=(
            "Multi-pass driver (22-layer-runner.R + 23-payload-application.R): run_rule_stage_"
            "layer_batch for clean and harmonize over committed rule workbooks. Each stage "
            "rewrites unit on pass 1 and no-ops on pass 2 -> converges (changed_value_count==0) "
            "in 2 passes. Asserts the converged data, stop_reason, passes_executed, converged, "
            "and matched_count match R — the full payload composition + convergence loop."
        ),
    ),
    "standardize": CaptureSpec(
        module="standardize",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _STRING_NORMALIZATION,
            _NUMERIC_COERCION,
            _STANDARDIZE_RULES_SETUP,
            _STANDARDIZE_ENGINE,
        ),
        fixture="synthetic/standardize_inputs.json",
        preamble=_STANDARDIZE_PREAMBLE,
        exports={
            "value": "res$data$value",
            "unit": "res$data$unit",
            "commodity": "res$data$commodity",
            "matched": "as.character(res$matched_count)",
            "unmatched": "as.character(res$unmatched_count)",
            "mrc_nrow": "as.character(nrow(mrc))",
            "mrc_applied": "mrc$applied_commodity_match_key",
            "mrc_affected": "as.character(mrc$affected_rows)",
            "mrc_effective": "as.character(mrc$unit_factor_effective)",
        },
        description=(
            "Unit standardization core (24-rules-setup.R + 24-standardize-engine.R): "
            "prepare_standardize_rules + apply_standardize_rules over fold / revert / two-stage "
            "match / affine convert. Asserts the converted value + unit, matched/unmatched counts, "
            "and the sorted matched_rule_counts (affected rows + effective multiplier) match R — "
            "incl. a specific prefixed rule, kg fallback, celsius->fahrenheit offset, and a "
            "comma-thousands prefix fold (parity risk #9)."
        ),
    ),
    "standardize_agg": CaptureSpec(
        module="standardize_agg",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _STRING_NORMALIZATION,
            _NUMERIC_COERCION,
            _AUDIT_DIAGNOSTICS,
            _STANDARDIZE_RULES_SETUP,
            _STANDARDIZE_AGGREGATION,
            _STANDARDIZE_ORCHESTRATION,
        ),
        fixture="synthetic/standardize_agg_inputs.json",
        preamble=_STANDARDIZE_AGG_PREAMBLE,
        exports={
            "agg_commodity": "agg$commodity",
            "agg_value": "agg$value",
            "agg_nrow": "as.character(nrow(agg))",
            "audit_commodity": "audit$commodity_key",
            "audit_affected": "as.character(audit$affected_rows)",
            "audit_effective": "as.character(audit$unit_factor_effective)",
            "audit_target": "audit$unit_target",
            "audit_nrow": "as.character(nrow(audit))",
        },
        description=(
            "Standardize aggregation + audit (24-standardize-aggregation.R + "
            "24-standardize-orchestration.R): aggregate_standardized_rows sums duplicate groups "
            "(all-NA group -> NA, unique rows kept) and build_standardize_layer_audit merges "
            "prepared rules with matched-rule counts (all-commodity rule attributed to each "
            "applied commodity). Both sorted; asserts the aggregated values + the audit "
            "commodity/affected/effective/target match R."
        ),
    ),
    "diagnostics": CaptureSpec(
        module="diagnostics",
        r_sources=(
            _GENERAL_CONSTANTS,
            _STRING_NORMALIZATION,
            _RULE_SUMMARIES,
            _STANDARDIZE_SUMMARIES,
        ),
        fixture="synthetic/diagnostics_inputs.json",
        preamble=_DIAGNOSTICS_PREAMBLE,
        exports={
            "cs_loop": "cs$loop",
            "cs_affected": "cs$affected_rows",
            "cs_value_source": "cs$value_source",
            "cs_value_target": "cs$value_target",
            "cs_column_target": "cs$column_target",
            "cu_nrow": "as.character(nrow(cu))",
            "cu_column_source": "cu$column_source",
            "cu_value_source_raw": "cu$value_source_raw",
            "cu_affected": "as.character(cu$affected_rows)",
            "ss_affected": "as.character(ss$affected_rows)",
            "ss_commodity": "ss$commodity_key",
            "ss_unit_target": "ss$unit_target",
            "su_nrow": "as.character(nrow(su))",
            "su_commodity": "su$commodity_key",
            "su_unit_source": "su$unit_source",
            "su_affected": "as.character(su$affected_rows)",
        },
        description=(
            "Postpro diagnostics summaries (25-rule-summaries.R + 25-standardize-summaries.R): "
            "summarize_stage_rules (value_source/target filled from *_result), "
            "build_unmatched_rule_summary (anti-join with NA-matching), "
            "summarize_standardize_rules, and build_unmatched_standardize_rule_summary via the "
            "normalized-key counts branch (an "
            "all-commodity rule matched by counts leaves the specific rule unmatched)."
        ),
    ),
    "export_processed_data": CaptureSpec(
        module="export_processed_data",
        r_sources=(_WRITE_PROCESSED_TABLE,),
        fixture="synthetic/export_processed_inputs.json",
        preamble=_EXPORT_PROCESSED_PREAMBLE,
        exports={"tsv_hex": "tsv_hex"},
        description=(
            "Processed-data TSV write (30-processed_data/03-write-processed-table-fast.R): "
            "write_processed_table_fast -> data.table::fwrite(sep = '\\t') over a harmonize-layer "
            "export frame (character columns + a Float64 value). The entire file is captured as a "
            "hex string, so the golden is the exact bytes — pinning the platform eol, fwrite's "
            "auto-quoting (embedded tab / newline / quote, empty-string vs NA), and double "
            "formatting (15 sig figs, fixed notation under scipen=999, trailing '.0' dropped). "
            "The polars write_csv-based writer must reproduce these bytes byte-for-byte."
        ),
    ),
    "export_lists": CaptureSpec(
        module="export_lists",
        r_sources=(_GENERAL_CONSTANTS, _COLLECT_LAYERS, _LISTS_01, _LISTS_02, _LISTS_03, _LISTS_04),
        fixture="synthetic/export_lists_inputs.json",
        preamble=_EXPORT_LISTS_PREAMBLE,
        exports=_EXPORT_LISTS_EXPORTS,
        description=(
            "Column-centric unique-list export (31-lists/*.R) over four layer objects (raw + "
            "clean/normalize/harmonize): per-(layer, column) unique values (drop-null, radix / "
            "code-point sort, '(blank)' prepended when any NA — parity risk #7 on the "
            "un-normalized raw layer), the sorted union of columns, the configured-column "
            "resolution (lists_to_export intersect union, config order; a configured-but-absent "
            "'footnotes' is dropped), and the identical-layer merge grouping + fixed sheet order "
            "per column (e.g. continent -> raw + clean_normalize_harmonize; commodity -> "
            "raw_clean + normalize_harmonize; unit -> raw_clean_normalize_harmonize)."
        ),
    ),
    "postpro_stage": CaptureSpec(
        module="postpro_stage",
        r_sources=(
            _GENERAL_CONSTANTS,
            _ASSERTIONS,
            _DATA_TABLE,
            _DIRECTORIES,
            _SORTING,
            _STRING_NORMALIZATION,
            _NUMERIC_COERCION,
            _STAGE_DEFINITIONS,
            _AUDIT_DIAGNOSTICS,
            _TEMPLATE_RULES,
            _RUNTIME_CACHE,
            _MATCHING_STRATEGY,
            _MATCHING_VALUES,
            _TARGET_APPLY,
            _SCHEMA_VALIDATION,
            _CONDITIONAL_GROUP,
            _FOOTNOTE_RULES,
            _PAYLOAD_APPLICATION,
            _STAGE_INPUTS,
            _CONTROLS_CACHE,
            _LAYER_RUNNER,
            _STANDARDIZE_RULES_SETUP,
            _STANDARDIZE_ENGINE,
            _STANDARDIZE_AGGREGATION,
            _STANDARDIZE_ORCHESTRATION,
        ),
        fixture="synthetic/postpro_stage_input.json",
        preamble=_POSTPRO_STAGE_PREAMBLE,
        exports=_POSTPRO_STAGE_EXPORTS,
        description=(
            "Stage-level run_postpro_pipeline over the frozen import output (orchestration "
            "replicated inline): audit value-parse -> clean -> standardize -> harmonize, each "
            "canonically sorted. Asserts every column of the clean / normalize / harmonize frames "
            "plus the clean & harmonize multi-pass diagnostics (stop_reason / passes_executed / "
            "converged / matched_count) match R. clean_ rewrites milk's unit (2 passes, 69 "
            "matched); the engine folds the '1000 ' unit prefix into value with no standardize "
            "rules; harmonize_ rewrites date's post-standardize unit (2 passes, 45 matched), "
            "proving harmonize runs on the standardized frame."
        ),
    ),
}
