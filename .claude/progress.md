# Progress

Session state for the migration + `/autocode` loop. Durable notes only (no scratch).

> **Normalization policy update (2026-07-29):** string / header / dataset-name normalization no
> longer reproduces R's ICU `Latin-ASCII`. `transliterate_ascii_lower` implements the documented
> POLICY (NFD diacritic strip + lowercase; any char with no ASCII base is dropped by the
> non-alnum step) — no ICU table, no `anyascii`, no character-specific overrides. Removes ICU
> quirks such as `Philippines®` → `philippines r` (now `philippines`). Value sums / row counts
> unchanged; verified by policy tests, not R goldens. Historical entries below that describe the
> `anyascii` / ICU-table approach are SUPERSEDED. See [r-to-python-mapping.md](docs/r-to-python-mapping.md) risk #1.

## Phase 0 — Foundation + Stage 0 — ✅ complete (2026-07-20)

Built the complete Python foundation for the R→Python migration:

- **Tooling:** `pyproject.toml` (hatchling, `requires-python>=3.11`), deps polars/pydantic/
  pydantic-settings/rich/typer/fastexcel/xlsxwriter/openpyxl; dev ruff/mypy/pytest.
  Ruff (E,W,F,I,N,UP,B,A,C4,SIM,PTH,ARG,RUF,D), mypy strict, pytest (`pythonpath=src`).
- **Stage 0 (setup) fully implemented + tested:** `constants` (frozen dataclasses mirroring
  `get_pipeline_constants`, `lru_cache`), `config`/`load_pipeline_config`, `RuntimeOptions`,
  `directories` (audit-subtree contract), `paths` (`here()` analogue), `errors`, `runner`, and
  helpers (`strings` w/ policy NFD transliteration, `numeric`, `sorting`, `frames`,
  `checkpoints`, `time_format`, `tokens`, `assertions`, `console`).
- **Contracts + scaffold:** typed `ImportResult`/`PostproResult`/`ExportResult` in
  `contracts.py`; stages 1–3 scaffolded (packages + runner stubs raising
  `StageNotImplementedError`; sub-package docstrings double as the per-module migration spec).
- **Orchestration:** `run_pipeline` + typer CLI (`whep-digitize run|bootstrap`).
- **AI layer:** `.claude/docs/` (architecture, codebase-map, constants-and-options,
  conventions, common-changes, r-to-python-mapping, migration-roadmap), guidelines
  (migration/refactoring/performance/testing/constants), skills (migrate-module,
  parity-check, migration-status), autocode command + `autocode.toml`.

**Gates:** ruff clean · mypy strict clean (48 files) · **61 tests pass** · CLI smoke OK
(bootstrap builds the full tree; run stops cleanly at ingest).

Notable decision: `alert_*` console markers are ASCII-only (a Unicode check mark crashed
rich's legacy-Windows renderer under cp1252).

## Phase 0.5 — R↔Python parity infrastructure — ✅ complete (2026-07-20)

Stood up the golden-capture harness **before** migrating any module (no module ported yet).

**Frozen input corpus** — `tests/fixtures/` (committed, immutable):

- `corpus/` — 6 real raw workbooks (one smallest-per-category: crops / livestock /
  population / inputs / land / trade), copied verbatim from
  `<whep-digitalization>/data/1-import/10-raw_import/`, mirroring the
  `<yearbook>/<yearbook>_<category>/` layout so it is a drop-in raw root for future ingest
  (Stage 1) parity (~37 KB total).
- `synthetic/normalize_string_inputs.json` — REMOVED (2026-07-29): string normalization no longer
  targets R/ICU parity, so its edge cases (`ß`, `½`, `œ`, …) moved to policy tests
  (`tests/setup/test_helpers.py`). See the normalization-policy note at the top.

**Harness** — `tests/parity/` (committed reusable pattern):

- `r_harness.py` — renders an *ephemeral* R bootstrap (sources R helpers by **absolute path**,
  no `here()`; deterministic options + `LC_COLLATE=C`), runs it via `Rscript`, writes JSON
  goldens, and **deletes the temp `.R` immediately** (DELETE-AFTER-USE). JSON (not TSV) is the
  golden format because only it round-trips the NA-vs-empty distinction (R `NA` ⇄ `null` ⇄
  Python `None`) that match keys depend on.
- `registry.py` — declarative `CaptureSpec`s (R sources + fixture + export expressions).
- `capture.py` — CLI to (re)generate goldens. `test_string_normalization_parity.py` —
  `@pytest.mark.parity` compare test (skips with a regen hint if goldens are absent).
- Env overrides: `WHEP_RSCRIPT`, `WHEP_R_REPO` (defaults: R 4.6.0 install; sibling repo).

**Goldens** — `tests/golden/<module>/*.json` (gitignored; regenerable, never committed).

**Proof (round-trip green):** `normalize_string` + `clean_footnote` captured from R and
matched byte-for-byte by the polars port over every edge case (incl. `ß`→`ss`, `½`→`1 2`,
`œ`→`oe`) — the top-ranked parity risk, de-risked.

**Frozen-corpus location + capture command:**

```bash
# Inputs (committed):  tests/fixtures/{corpus,synthetic}/
# Goldens (gitignored): tests/golden/<module>/
.venv/Scripts/python.exe tests/parity/capture.py                    # (re)generate all goldens
.venv/Scripts/python.exe tests/parity/capture.py string_normalization
.venv/Scripts/python.exe -m pytest -m parity                        # verify Python matches R
```

## Phase 1a — ingest file_io (discovery + metadata) — ✅ complete (2026-07-20)

First ingest modules ported (`r/1-import_pipeline/10-file_io/`), bottom-up per the DAG:

- **`ingest/file_io/metadata.py`** (`10-metadata.R`) — `extract_file_metadata` +
  `build_empty_file_metadata`. Reuses `helpers.tokens` (`extract_yearbook` / `extract_commodity`)
  for the positional convention (yearbook = token 2 + first `^\d{4}$` token; commodity =
  tokens 7+, extension stripped from last). Basename via `PurePosixPath(p).name`; ASCII flag
  via `str.isascii()` (== R `stringi::stri_enc_isascii`); non-ASCII → verbatim error message.
  Frames built with an explicit `pl.Schema` so all-null token columns stay `String`, not `Null`.
- **`ingest/file_io/discovery.py`** (`10-discovery.R`) — `discover_files` +
  `discover_pipeline_files`. `Path.rglob` + `is_file()` + case-sensitive `.xlsx` `endswith`
  (R globs `*.xlsx` case-sensitively). Emits forward-slash paths (`as_posix`) **sorted by full
  path string** to match `fs::dir_ls` C-locale/radix order deterministically (parity risk #7).
  Empty folder → `warnings.warn` + empty frame (R `cli_warn`).

**Parity** — new `file_metadata` `CaptureSpec` + committed fixture
`synthetic/file_metadata_inputs.json` (6 real corpus paths + edge cases: `<=6` tokens →
no commodity, no 4-digit token / `<2` tokens → no yearbook, first-year-wins, non-ASCII
`café`). Golden captured per output column (atomic `write_golden`); all 6 columns matched
byte-for-byte. `fs` confirmed installed in the R 4.6.0 env. Discovery's filesystem behaviour
(sort order, posix form, recursion/filtering, empty/blank/missing) covered by functional
tests in `tests/ingest/test_file_io.py` (verified against R `fs::dir_ls` ground truth).

**Gates:** ruff clean · mypy strict clean (56 files) · **88 tests pass** (25 new: 19
functional + 6 parity). Pre-existing `ruff format` nit in `tests/parity/r_harness.py` left
untouched (out of scope).

## Phase 1b (partial) — ingest reading: header normalization — ✅ complete (2026-07-21)

Ported `11-header-normalization.R` → `ingest/reading/header_normalization.py` (HIGH risk,
parity-critical):

- **`normalize_header_names`** (+ singular `normalize_header_name`) — the exact ordered
  chain: trim → collapse whitespace → strip padding around `/`/`-` → `Latin-ASCII; Lower`
  transliterate → non-`[a-z0-9-/]` runs to `_` → collapse `_` → trim `_`. Reproduces the R
  fast-path short-circuit (already-clean vector with no collapsible/leading/trailing `_`
  returns verbatim). `None`/`NA` pass through positionally.
- **`resolve_canonical_header_renames`** → `HeaderRenames(old, new)` — canonical match +
  `country`→`polity` alias with ALL R collision guards ported exactly: `has_exact` skip,
  alias target-present, alias-source-already-renamed, and `duplicated(alias_new)` (computed
  over the full surviving vector, ANDed with the `%in% old_names` filter — a sequential
  short-circuit would diverge). Drops `old == new` no-ops.
- **`validate_header_normalization`** — collision detection via `Counter` (first-appearance
  order). Returns a deterministic message (sheet, file basename, colliding keys); the R
  `cli::format_error` box formatting is intentionally not reproduced (errors use the Python
  messaging convention).

**Shared transliteration:** promoted `strings._to_ascii_lower` → public
`strings.transliterate_ascii_lower` (behaviour-preserving) so header keys and match keys
fold through ONE implementation — the single home for any future ICU-divergence override.

**Parity (top project risk de-risked):** new `header_normalization` `CaptureSpec` + committed
fixture `synthetic/header_names_inputs.json` (accents/ligatures/symbols: café, São, Zürich,
Ñoño, naïve, Øresund, Åland, groß, **½**, œuvre, æsir + whitespace/separator/punctuation/
underscore/empty/fast-path cases). Divergence hunt: `anyascii` matched R ICU `Latin-ASCII`
**byte-for-byte on every header, zero divergences** — including `½`→`1/2_unit` (ASCII `/`
preserved by the header pattern, the case masked in string-normalization). **No override
needed.** Renames goldens cover all guards; `validate_dups` covers detection (captured
cli-free). Non-ASCII kept in the JSON fixture (not R script literals) to avoid Windows
cp1252 corruption.

**Gates:** ruff clean · mypy strict clean (59 files) · **126 tests pass** (+38: 33
functional + 5 parity). Pre-existing `ruff format` nit in `tests/parity/r_harness.py` still
left untouched (out of scope).

## Phase 1b (rest) — ingest reading: read_utils + sheet_read + batching — ✅ complete (2026-07-21)

Completed the reading sub-stage (`r/1-import_pipeline/11-reading/`), bottom-up:

- **`read_utils.py`** (`11-read-utils.R`) — typed `(data, errors)` plumbing: `ReadResult`,
  `SafeReadResult[T]`, `safe_execute_read` (try/except → collected error, R `tryCatch`),
  `create_empty_read_result`, `has_read_errors`, `normalize_pipeline_read_result`. Error
  strings are deterministic (R `cli::format_error` box art not reproduced).
- **`sheet_read.py`** (`11-sheet-read.R`) — `read_excel_sheet`: all-as-text read
  (`pl.read_excel(engine="calamine", infer_schema_length=0)`), header normalize +
  canonical/alias rename, base-column non-empty filter, `variable` := sheet name (overwrite
  in place if present, else append — R `:=`). `read_file_sheets` row-binds sheets via
  `pl.concat(how="diagonal")` (R `rbindlist(use.names, fill)`) + non-ASCII sheet-name warning;
  `compute_non_empty_base_rows` via `any_horizontal`.
- **`batching.py`** (`11-batching.R`) — `split_workbook_batches`,
  `resolve_import_workbook_batch_size`, `resolve_import_effective_workers`
  (`"auto"` → `min(8, cpu-1)`, explicit int honored, `<1` → sequential), `read_workbook_batch`
  (dedup unique paths, map back preserving order). Deferred to the runner phase: the parallel
  `read_pipeline_files` + `import_future_scheduling` (no direct `ProcessPoolExecutor` analogue).

**Key parity finding:** readxl and calamine disagree on the RAW read (readxl keeps blank
source rows, calamine drops them — 23 vs 18 rows on the date workbook), but
`read_excel_sheet`'s base-column filter removes exactly those rows, so the **filtered output
is byte-identical**. Verified: all 10 output columns + column order (`country`→`polity`,
`variable` last) + row count match the R golden.

**Harness extension (reusable):** `CaptureSpec.fixture` is now optional and a `preamble` +
`fixtures_dir` R var were added, so a capture can read a committed corpus workbook and capture
its columns (the pattern all frame-producing ingest modules will reuse). New `sheet_read`
CaptureSpec reads a real corpus sheet via readxl and captures the filtered frame. Confirmed
`readxl`/`cli`/`future.apply` available in the R 4.6.0 env. Divergences documented: polars
immutability (no per-duplicate deep copy), deterministic error messages.

**Gates:** ruff clean · mypy strict clean (64 files) · **167 tests pass** (+41). Added mypy
overrides for the untyped Excel-IO deps (`fastexcel`, `xlsxwriter`). Pre-existing `ruff
format` nit in `r_harness.py` resolved incidentally (the file was edited for the extension).

## Phase 1c (partial) — ingest transform: transform_utils + reshape — ✅ complete (2026-07-21)

Ported the wide->long transform core (`r/1-import_pipeline/12-transform/`), bottom-up:

- **`transform_utils.py`** (`12-transform-utils.R`) — `identify_year_columns` (candidates =
  columns not in `column_order \ {year,value}`, kept when matching `^\d{4}(-\d{4})?$`, in
  column order), `normalize_key_fields` (add missing base cols null; `commodity` :=
  normalized scalar; normalize `variable`/`hemisphere`/`continent`/`polity`; clean
  `footnotes`; `unit` left raw), `convert_year_columns` (Excel `.0` strip, `YYYY-NN`->`YYYY`,
  `YYYY-NN/YYYY-NN`->`YYYY-YYYY`, then a **fatal** duplicate-collision guard → `ValidationError`).
- **`reshape.py`** (`12-reshape.R`) — `reshape_to_long` (the `melt`->`unpivot`), `add_metadata`
  (document/notes/yearbook), `transform_file_df` (full per-file chain), `resolve_commodity_name`,
  `build_empty_transform_result`, and the `TransformResult(wide_raw, long_raw)` type.

**Parity risk #2 handled:** the `whep_year_columns` attribute is NOT carried — `reshape_to_long`
recomputes year columns via `identify_year_columns`. `unpivot(index=available_id, on=year_cols)`
drops exactly the columns `melt(id.vars, measure.vars)` drops (verified: a non-id/non-year
column is dropped identically). **Confirmed polars `unpivot` produces the same variable-major
row order as data.table `melt`** — the full `transform_file_df` long frame matched the R golden
byte-for-byte: 12 columns in order, 45 rows (72 melted − 27 null-value), every cell equal
(incl. accent-folded polity values and the `drop_na_value_rows` filtering).

**Capture:** new `transform` CaptureSpec reads a real corpus sheet then runs the full R
`transform_file_df` (reuses the harness `preamble`/`fixtures_dir`), capturing the long frame
column-by-column. Divergence documented: R's year-column `as.character` coercion is a no-op
(calamine reads all-as-text).

**Gates:** ruff clean · mypy strict clean (68 files) · **202 tests pass** (+35: 22 functional
+ 13 parity).

## Phase 1c (rest) — ingest transform: processing (fused + parallel) — ✅ complete (2026-07-21)

Ported `12-processing.R` → `ingest/transform/processing.py`, completing Stage 1c:

- **`transform_single_file`** — resolve commodity + `transform_file_df` for one file; `None` for
  a 0-row wide frame (R `NULL`, dropped downstream); explicit `isinstance` guards on
  `file_name` / `yearbook` (ValidationError, and mypy-narrowing).
- **`read_transform_pipeline_files`** — the fused read+transform-per-batch path
  (+ `ReadTransformResult`). Sequential by default; `ProcessPoolExecutor` when
  `resolve_import_effective_workers > 1` and `> 1` batch, with a graceful sequential fallback on
  `BrokenProcessPool` / `OSError`. **Determinism:** `executor.map` preserves submission order,
  so combined output is byte-identical regardless of worker count.
- **Config-not-picklable workaround:** `Config` nests `mappingproxy` (unpicklable), so workers
  receive the picklable `(dataset_name, project_root)` and rebuild an identical config via
  `load_pipeline_config` (config is a pure function of those + the frozen constants).

**Parity (the headline result):** new `processing` CaptureSpec discovers the whole corpus and
runs the full R `read_transform_pipeline_files`. Python **sequential AND parallel** (4 workers,
one batch per file) both match the R golden byte-for-byte (313 rows × 12 cols) — verified in
`tests/parity/test_processing_parity.py`. ProcessPoolExecutor spawn works under pytest.

**Transliteration divergence found + fixed (top project risk realized).** The corpus surfaced
one cell where `anyascii` ≠ ICU: `"belgian congo¹"` — ICU leaves superscript `¹` (U+00B9)
unchanged (→ stripped by the non-alnum step) while `anyascii` folds it to `"1"` (kept), giving
`belgian congo1`. Root cause: **ICU "Latin-ASCII" is conservative** (leaves most symbols) while
anyascii is aggressive (`£`→`GBP`, `°`→`deg`, `½`→`1/2` vs ICU `" 1/2"`, …). Fix: an ICU-derived
override table in the shared `strings.transliterate_ascii_lower` (identity codepoints +
fraction/`±`/`Ŋ` remaps over Latin-1 + super/subscripts + number forms). Regression tests in
`tests/setup/test_helpers.py`; the golden parity tests guard the rest. All prior parity
goldens (string/header/transform) still pass unchanged.

**Deferred:** the non-fused two-stage `process_files` / `transform_files_list` (R has both;
the fused path is what the runner uses) — will be added with the runner if needed.

**Gates:** ruff clean · mypy strict clean (71 files) · **232 tests pass** (+30). Stage 1c
(transform) is complete.

## Phase 1d (partial) — ingest output: validate — ✅ complete (2026-07-21)

Ported `13-validate.R` → `ingest/output/validate.py` (`validate_long_df_by_document` +
`ValidationResult`), the most intricate ingest module (parity risk #3). Runs the three
long-format checks for every document in one pass:

- **Document-major frame:** reorder rows so each document is contiguous in first-appearance
  order (via `_orig` min per document + stable sort), preserving within-document order (R
  `order(chmatch(...))`); per-document row id via `pl.int_range().over("document")`, absolute
  row position, document rank via `rle_id`.
- **4-key stable sort:** every error carries `(document_rank, type_rank, key_a, key_b)`; the
  combined errors sort by that tuple (R `setorder`) so within a document mandatory → year →
  duplicate errors interleave in the exact R order. `None`→`"NA"` coercion in messages mirrors
  R `as.character`.
- **current_year** is a parameter (defaults to system year, matching R `Sys.Date`) so the
  plausible-year range in messages is deterministic in tests.

**Parity:** new `validate` CaptureSpec over an interleaved multi-document fixture; the R
capture pins `Sys.Date` (→ `current_year` 2025), the Python parity test passes the same.
**Verbatim error strings AND their order match R byte-for-byte** (7 errors spanning
mandatory/year/duplicate across two interleaved documents, incl. `notes = NA` and `[1900,
2026]`), as does the document-major reordered data.

**Deferred:** the non-vectorized `validate_long_dt` + standalone helpers (the reference the
vectorized path replaces; the runner uses `_by_document`).

**Gates:** ruff clean · mypy strict clean (74 files) · **248 tests pass** (+16).

## Phase 1 COMPLETE — ingest output consolidate + runner wiring — ✅ (2026-07-22)

Closed out Stage 1 (ingest) end-to-end:

- **`output/consolidate.py`** (`13-output.R`) — `consolidate_audited_df` (drop `None` frames,
  `pl.concat(how="diagonal")` for R `rbindlist(use.names, fill)`, fill missing schema columns
  null, reorder to `column_order` with extras last) + `validate_output_column_order` (unique +
  full-target-schema check) + `ConsolidateResult`.
- **`runner.py`** (`run_import_pipeline.R`) — **removed `StageNotImplementedError`**; wired the
  full contract: `discover_pipeline_files` → `read_transform_pipeline_files` → `drop_na_value_rows`
  → `validate_long_df_by_document` → `consolidate_audited_df` → `sort_pipeline_stage_df` →
  `ImportResult(data, wide_raw, diagnostics)`. `current_year` param for deterministic validation.
  Deferred (output-preserving): R's `here::here` auto-sourcing / auto-run, checkpoint cache, and
  `progressr` bars (progress lands in Phase 5).

**STAGE-LEVEL parity (the milestone):** new `import_stage` CaptureSpec replicates the R
`run_import_pipeline` orchestration inline over the whole corpus. Python `run_import_pipeline`
matches R **byte-for-byte**: consolidated long frame 313×12 in canonical sort order (every
column), **all 232 validation-error strings verbatim + in order**, and reading-errors/warnings.
Updated the Stage-0 `test_ingest_stage_pending` contract test (ingest is no longer a stub;
postpro/export remain). Added a reusable `corpus_config` conftest fixture (raw dir → fixture
corpus).

**Gates:** ruff clean · mypy strict clean (78 files) · **271 tests pass** (+23). **Stage 1
(ingest) is done** — `run_import_pipeline` produces a parity-correct `ImportResult` on the
frozen corpus.

## Phase 2 (start) — postpro rule engine: matching_strategy + matching_values — ✅ (2026-07-22)

First two rule-engine modules (bottom of the Stage 2 critical-path DAG), ported together:

- **`rule_engine/matching_strategy.py`** (`23-matching-strategy.R`): `encode_target_rule_value`
  / `decode_target_rule_value` (NA/blank ⇄ `na_placeholder` `"..NA_INTERNAL.."`),
  `encode_rule_match_key` (normalize via `normalize_string` + NA → `na_match_key`
  `"..NA_MATCH_KEY.."`), and the strategy/normalization resolvers
  (`get_target_update_strategy_config`, `resolve_target_update_strategy`,
  `resolve_tokenized_target_condition_columns` → `("footnotes", "notes")`,
  `resolve_rule_match_normalization_settings`, fast-path toggle, empty overwrite-events frame).
  Returns typed frozen dataclasses instead of R named lists.
- **`rule_engine/matching_values.py`** (`23-matching-values.R`):
  `match_rule_target_condition_values` (tokenized `;`-membership + full-string match, explicit
  wildcard `__ANY__`, NA↔NA), `concatenate_existing_and_incoming_values` (order-preserving,
  existing-first token dedupe; existing-only passes through un-deduped), and
  `count_elementwise_value_changes` (the element-wise change count driving multi-pass
  convergence).
- **Parity risks hit:** #5 NA↔NA folding to `na_match_key` (both match paths) and #1
  `Latin-ASCII; Lower` transliteration inside match keys (reuses `strings.normalize_string`).
- **R quirk reproduced (not fixed):** in the tokenized path an empty-string current value never
  matches — R keys the token lookup by the current value and base R cannot retrieve a list
  element by an empty-string name (`list[[""]]` → `NULL`). Documented + regression-tested.
- **Parity:** new `matching` `CaptureSpec` + `tests/fixtures/synthetic/matching_values_inputs.json`
  (16 rows: unicode diacritics/ligatures/`ß`/`½`, Greek in the no-transliteration concat path,
  NA/empty/wildcard/duplicate). 8 goldens; `tests/parity/test_matching_parity.py` matches R
  byte-for-byte. Unit suite `tests/postpro/test_matching.py`.

**Gates:** ruff clean · ruff-format clean · mypy strict clean (82 files) · **318 tests pass**
(+47: 39 unit + 8 parity). Next on the critical path: `rule_engine/target_apply.py`
(`last_rule_wins` + overwrite events, `concatenate`).

## Phase 2 — postpro rule engine: target_apply — ✅ (2026-07-22)

`rule_engine/target_apply.py` (`23-target-apply.R`, `apply_target_updates_with_strategy`) —
the strategy-dispatch core, built on `matching_strategy` + `matching_values`:

- **last_rule_wins:** stable-sort candidates by the order columns (setorderv default: ascending,
  NAs first), then group-last per row. A *fast path* (each row updated once) skips the collapse;
  the *slow path* emits an overwrite-event row per dataset row that got >1 **distinct** candidate
  (`unique_candidate_count > 1`).
- **concatenate:** per-row paste of candidates, then order-preserving existing-first token merge.
- **condition matching + wildcard:** conditioned updates are filtered by
  `match_rule_target_condition_values`; wildcard candidates whose value is already present in the
  current cell are dropped. Surviving conditioned rows are appended after the unconditional rows
  (R `rbindlist` order).
- **Functional scatter (parity risk #10):** R's in-place `data.table::set` becomes a join-back on
  a synthesized row index + `when/then/otherwise`; the updated frame is returned in the new
  `TargetApplyResult` (`applied`, `dataset`, `overwrite_events`, `changed_value_count`) instead of
  mutating the argument.
- **R behaviors preserved:** the wildcard token only matches for tokenized targets (else literal);
  `candidate_values` reproduces R `paste()` — a null candidate becomes the literal `"NA"`; a null
  `selected_value` rides through.
- **Parity:** new `target_apply` `CaptureSpec` + `tests/fixtures/synthetic/target_apply_inputs.json`
  (4 scenarios: lrw fast path, lrw slow path with a conflict + null candidate, concatenate,
  wildcard-removal). 26 goldens; `tests/parity/test_target_apply_parity.py` matches R byte-for-byte
  (mutated column, `applied`, `changed_value_count`, full overwrite-events frame). Unit suite
  `tests/postpro/test_target_apply.py`.

**Gates:** ruff + ruff-format clean · mypy strict clean (85 files) · **342 tests pass** (+24: 20
unit + 4 parity). Next on the critical path: `rule_engine/conditional_group.py` (cartesian keyed
join → source+target scatter → audit), which drives `apply_target_updates_with_strategy`.

## Phase 2 — postpro rule engine: schema_validation (+ stage_definitions dep) — ✅ (2026-07-22)

Ported `23-schema-validation.R` plus its small unported dependency `21-stage-definitions.R`:

- **`utilities/stage_definitions.py`** (`21-stage-definitions.R`): `get_canonical_rule_columns`,
  `get_postpro_stage_names`, `validate_postpro_stage_name` (exact match — R's `match.arg`
  abbreviation is out of scope; callers pass full names), `get_stage_{source,target}_value_column`.
  Added `stage_source_value_column`/`stage_target_value_column` to `constants.Postpro`.
- **`rule_engine/schema_validation.py`** (`23-schema-validation.R`):
  - `coerce_rule_schema` — strip `clean_`/`harmonize_` prefix (`str.removeprefix`), enforce the 6
    canonical columns (`value_source` optional → synthesized null), carry
    `source_value_column_present`; aborts on duplicate-after-normalization / missing-required /
    unexpected columns.
  - `validate_canonical_rules` — schema/required-value/dataset-column presence, **duplicate-key**
    abort, target/source **conflict** aborts (structurally present but subsumed by the
    duplicate-key check, as in R), and `check_type_compatibility` (no-op on the all-text String
    dataset; numeric/integer/Date branches faithful for non-string columns).
  - `build_conditional_rule_dictionary` — group by `(column_source, column_target)`; within-group
    order is code-point radix + NA-last (parity risk #7); **group order reproduces R's
    `interaction` factor order** = sorted by `(column_target, column_source)` (verified against the
    golden), with null source/target rows dropped (R `split` drops NA levels). Returns
    `list[pl.DataFrame]` (the consumer iterates positionally and reads `column_source[0]`).
  - Supporting: `normalize_rule_values_for_validation` (blank/NA → `na_placeholder`),
    `ensure_rule_referenced_columns` (functional column add; the R duplicate-dataset-column guard
    is a structurally-unreachable mirror — polars forbids duplicate columns).
- **Parity:** new `schema_validation` `CaptureSpec` + unicode/case/NA fixture. 15 goldens:
  flattened dictionary groups (group order + within-group `"Apple"`<`"apple"`<`"éclair"`<NA),
  coerce in both flag states, and validate abort-or-not (valid / duplicate-key / missing-column,
  captured with R `try()`). `tests/parity/test_schema_validation_parity.py` matches byte-for-byte.

**Gates:** ruff + ruff-format clean · mypy strict clean (89 files) · **373 tests pass** (+31: 25
unit + 6 parity). Next on the critical path: `rule_engine/conditional_group.py` and
`rule_engine/footnote_rules.py`, then `payload_application.py` wires them together.

## Phase 2 — postpro rule engine: conditional_group — ✅ (2026-07-22)

`rule_engine/conditional_group.py` (`23-conditional-group.R`, `apply_conditional_rule_group` +
`prepare_conditional_rule_group`) — the source→target group applicator that drives
`apply_target_updates_with_strategy`:

- **Cartesian keyed join:** each dataset row is left-joined to the group's rules on the encoded
  `source_key` (multi-match fans out). data.table's Y-then-X row order (dataset row, then rule
  order) is reproduced by an explicit `(row_id, __rule_order__)` sort — the source/target
  last-rule-wins reductions depend on it.
- **Target-condition match** on the matched subset (reuses `match_rule_target_condition_values`);
  `matched_row_mask = source_matched & target_condition`. Computing the condition over every
  joined row then AND-ing is equivalent to R's matched-subset computation.
- **Source rewrite** (functional scatter, last-rule-wins per row; change count over the
  un-deduplicated before/after vectors, matching R) then **target update** via
  `apply_target_updates_with_strategy` (`apply_condition_match=False`, `order_columns=["row_id"]`).
- **Encoded-NA audit join-back:** group audited rows by `(source_key, target_key,
  value_source_result, value_target_result_encoded)`, join back to the keyed rules, order by
  `(column_source, column_target, value_source_raw, value_target_raw)`.
- **Independent `changed_columns`** (parity focus): a group whose only effect was a source rewrite
  marks the **source** column, not the target. Returns `ConditionalGroupResult` (functional; R
  mutated the frame in place — risk #10).
- **Parity:** new `conditional_group` `CaptureSpec` + 4-scenario fixture (M: 2 rules over 4 rows
  incl. a `"Café"→"COFFEE"` transliteration match + audit grouping/affected-rows; SO: source-only;
  TO: target-only; NM: no-match). 31 goldens; `tests/parity/test_conditional_group_parity.py`
  matches R byte-for-byte (mutated columns, `changed_value_count`, `changed_columns`, full audit
  frame). Unit suite `tests/postpro/test_conditional_group.py`.

**Gates:** ruff + ruff-format clean · mypy strict clean (92 files) · **391 tests pass** (+18: 13
unit + 5 parity). Rule engine: 5 of 7 modules done. Next: `rule_engine/footnote_rules.py` (the
explode→match→resolve→reconstruct — the hardest single port), then `payload_application.py` wires
footnote rules + conditional groups per rule file.

## Phase 2 — postpro rule engine: footnote_rules — ✅ (2026-07-22)

`rule_engine/footnote_rules.py` (`23-footnote-rules.R`, `apply_footnote_rules`) — the top-risk
module: the `;`-explode / rule-match / resolve / reconstruct engine for footnote-sourced rules.

- **R `strsplit` semantics reproduced exactly** (verified by an R probe): `NA` → one `NA` token,
  `""` → zero tokens, and a **single trailing empty field is dropped** (`"a;"`→`["a"]`,
  `";;"`→`["","" ]`) while leading/internal empties are kept. Exploded via a Python row loop
  (`_r_strsplit`) since polars `str.split` keeps trailing empties and can't express this.
- **Cartesian join** of each footnote token to the rules on the source key; Y-then-X order
  reproduced via a `(row_id, footnote_index, __rule_order__)` sort.
- **Conditional-target gating:** for rules targeting a data column with a condition, the match is
  kept only when the current target value satisfies it (per-column normalization mirrors R).
- **Precedence resolution** per `(row_id, footnote_index)`: **remove > replace > original**, with
  the first replacement (join order) winning; reconstruct in `footnote_index` order (`;`-joined,
  `NA` tokens dropped, all-`NA`/empty rows → `NA`).
- **Target updates** via `apply_target_updates_with_strategy` (per target column,
  `order_columns=["row_id","footnote_index"]`).
- **Footnote change count** vs a snapshot before-image (functional — no in-place aliasing, so no
  deep-copy needed); `changed_columns` marks `"footnotes"` only when the text actually changed.
- **Audit** over matched, non-no-op token matches grouped by the 5 rule-value keys.
- **Parity:** new `footnote_rules` `CaptureSpec` + one rich 12-row fixture (replace / remove /
  multi-token / precedence / NA / `""` / trailing-`;` / whitespace / conditional-target /
  transliteration / no-op). 17 goldens; `tests/parity/test_footnote_rules_parity.py` matches R
  byte-for-byte (reconstructed footnotes, mutated target, change count, changed_columns, full
  audit frame). Unit suite `tests/postpro/test_footnote_rules.py`.

**Gates:** ruff + ruff-format clean · mypy strict clean (95 files) · **412 tests pass** (+21: 19
unit + 2 parity). **Rule engine: 6 of 7 modules done** — only `payload_application.py` remains
(the per-rule-file orchestration that splits footnote vs standard rules and applies footnote
rules then each conditional group). After that: `clean_harmonize/` (multi-pass driver), audit,
standardize_units, diagnostics, then export (Stage 3).

## Phase 2 — postpro non-engine (Track C): data audit — ✅ (2026-07-22)

`postpro/audit/` (`20-data_audit/`, all four files) — the data-audit stage. `audit_data_output`
runs master validation, exports a highlighted invalid-row workbook, and parses `value` to
`Float64`, returning a typed `AuditResult(audited, findings, invalid_row_index, report_path)`
(R returned only the parsed frame + a side-effect file).

- **Parity risk #8 reproduced exactly** — the audit regex `^[0-9]+(\.[0-9]+)?$`
  (`audit_numeric_string`, added to `constants.Patterns`) is *stricter* than the float parser:
  `-3.5`, `3.`, `.5`, `1e5`, `+3` are all **flagged as findings yet still parse** (verified both
  engines agree numerically: polars `cast(Float64, strict=False)` == `readr::parse_double`).
- **Invalid rows are kept** in the audited output (not dropped); `value` NAs for unparseable.
- **Validators** (`validation.py`): `audit_character_non_empty` (null/blank-after-trim, `trimws`
  class `[ \t\r\n]`) + `audit_numeric_string` (non-null & regex miss; NA skipped). 1-based
  `row_index` (R `which`). Registry + plan + `run_master_validation` (unsupported → warn,
  `selected_validations` filter, sorted-unique `invalid_row_index`), findings in plan order.
- **Excel export** (`export.py`): first **openpyxl** use — `PatternFill` + bold `Font` + thick
  `Border` from `ErrorHighlightStyle`; `source_row_index` keying, `document` stable-sort
  (nulls last), 1-based row/col + header offset, technical columns hidden, empty-note branch.
  Reuses `delete_directory_if_exists` / `ensure_output_directories`. `openpyxl.*` added to the
  mypy import overrides.
- **Config** (`config.py`): `empty_audit_findings` schema, audit-type/message constants,
  `validate_audit_config`, `prepare_audit_root`, `resolve_audit_output_paths`.
- **Parity:** new `data_audit` `CaptureSpec` + 15-row fixture (the full parser-vs-regex
  divergence set). 6 goldens; `tests/parity/test_data_audit_parity.py` matches R on the findings
  table, `invalid_row_index`, and the parsed value column (numeric compare). Unit suite
  `tests/postpro/test_data_audit.py` (incl. openpyxl highlight readback).

**Gates:** ruff + ruff-format clean · mypy strict clean (101 files) · **443 tests pass** (+31: 29
unit + 2 parity). **Postpro Track C started** — audit done; standardize_units, diagnostics,
utilities, and `clean_harmonize/` (multi-pass driver) remain, plus rule-engine
`payload_application.py` and export (Stage 3).

## Phase 2 — postpro non-engine (Track C): utilities — ✅ (2026-07-22)

`postpro/utilities/*` (`21-*`, C2) — the four non-`stage_definitions` utilities. Prereq for the
rule-engine multi-pass session (B6).

- **`output_roots.py`** — `get_postpro_output_paths` / `initialize_postpro_output_root` →
  typed `PostproOutputPaths` (audit / diagnostics / templates / runtime_cache), created via the
  shared `ensure_directories_exist`. R's `%||%` per-dir fallback is unnecessary (the typed Config
  always resolves them).
- **`diagnostics.py`** — `build_layer_diagnostics` → `LayerDiagnostics`: `matched_count` =
  Σ`affected_rows` (0 when empty / column absent, mirroring R `sum(NULL)`), `unmatched_count` =
  `max(rows_in − matched, 0)`, pass/warn status + message. The non-deterministic wall-clock
  timestamp and the write-only `layer_name`/`rows_out` are dropped from the reduced contract
  (`rows_out`/`layer_name` validated for interface parity).
- **`templates.py`** — **`read_rule_table`** (the focus): all-as-text reads (calamine
  `infer_schema_length=0` / `pl.read_csv` no-infer) so `"007"`/`"1000.0"` keep their source
  string; the xlsx **sheet schema-matching heuristic** (strip `clean_`/`harmonize_` prefix → keep
  sheets with no duplicate/unexpected columns and all required present → row-bind; abort if none).
  Plus `write_stage_rule_template`/`generate_postpro_rule_templates` (openpyxl 2-sheet template)
  and `discover_stage_rule_files`/`load_stage_rule_payloads` (deterministic prefix discovery).
- **`payload_cache.py`** — 2-level (memory `dict` + pickle disk) rule-payload cache keyed by an
  **md5 fingerprint of the ordered rule files** (`build_stage_payload_cache_key`), deterministic
  prune (lowest sorted keys), `get_cached_stage_payload_bundle` (memory→disk→build+persist).
  **Off by default**; disk uses pickle (the `saveRDS` analogue — parquet can't hold the nested
  bundle). R's auto-enable-when-`runtime_cache_dir`-set is intentionally not reproduced.
- **Parity:** new `utilities` `CaptureSpec` + committed xlsx fixture `clean_rules_sample.xlsx`
  (matching `clean_rules` sheet with numeric-looking codes + a skipped `guidance` sheet). 16
  goldens; `tests/parity/test_utilities_parity.py` matches R on `read_rule_table` (columns/values,
  all-as-text) and `build_layer_diagnostics` (matched + empty). Unit suite
  `tests/postpro/test_utilities.py`.

**Gates:** ruff + ruff-format + mypy strict clean (107 files) · **467 tests pass** (+24: 22 unit +
2 parity). **Track C: audit + utilities done.** Remaining Track C: `clean_harmonize/`
(multi-pass), `standardize_units/`, `diagnostics/`; plus rule-engine `payload_application.py`
(B6, now unblocked by C2) and export (Stage 3).

**CI note:** the repo's GitHub Actions `quality` workflow hangs to the 6h timeout and is cancelled
on every run (never green) — all merges land on local gates only. Flagged as a background task to
fix the workflow.

## Phase 2 — postpro multi-pass driver (B6): payload_application + clean_harmonize — ✅ (2026-07-23)

`rule_engine/payload_application.py` (`23-payload-application.R`) + `clean_harmonize/*` (`22-*`) —
the Stage-2 critical path. Unblocked by C2 (payload loaders). **Rule engine now complete (7/7).**

- **`payload_application.py`** — `prepare_rule_payload_execution_plan` (split footnote-source vs
  standard rules; `build_conditional_rule_dictionary` for group order) + `apply_rule_payload`
  (footnote rules first, then each conditional group in order; accumulate audit / overwrite /
  change count / changed_columns; `trigger_columns` gate). Composes the B4/B5 appliers.
- **`clean_harmonize/stage_inputs.py`** — post-loop `;`-cell canonicalization of `notes`/
  `footnotes` (split → trim → drop-empty → dedupe → radix-sort; blank→null; per-distinct-value
  memoized) and drop of an all-null `footnotes` column.
- **`clean_harmonize/controls_cache.py`** — `resolve_stage_multi_pass_controls` (from constants)
  + **cycle detection** replacing R `serialize()` with a deterministic content hash (parity
  risk #6): `df.hash_rows()` folded via blake2b, screened by a cheap fingerprint (row count +
  per-column dtype/null/byte-length). The off-by-default schema-validation memoization cache is
  intentionally not ported (no output impact).
- **`clean_harmonize/layer_runner.py`** — `run_rule_stage_layer_batch` (+ `run_cleaning_` /
  `run_harmonize_layer_batch`) → typed `StageLayerResult` (R used data.table attributes). Loads
  payloads (C2), validates each once, then loops passes (max 10): apply all payloads, stop on
  `changed_value_count==0` (converged) / repeated state (cycle → warn|abort) / max passes.
  Match-key normalization on pass 1 only. Post-loop canonicalize + drop-empty-footnotes.
- **Parity:** new `layer_batch` `CaptureSpec` + committed rule workbooks
  (`fixtures/rule_files/{clean,harmonize}/*.xlsx`) + dataset fixture; the R capture builds an
  inline config pointing at them (cache disabled) and runs both stages. `test_layer_batch_parity`
  matches R on converged data, `stop_reason`, `passes_executed`, `converged`, `matched_count`
  (each stage converges in 2 passes). Also a `utilities`-style `apply_rule_payload` path is
  covered by unit tests. Unit suite `tests/postpro/test_clean_harmonize.py` (incl. cycle-detection
  via oscillating rules → warn, and pass-1 normalization / drop-footnotes).

**Gates:** ruff + ruff-format + mypy strict clean (113 files) · **483 tests pass** (+16: 14 unit +
2 parity). **Rule engine 7/7 done; clean_harmonize done.** E1 (postpro 9-step runner) now needs
only Track C's C4 (standardize agg + orchestration) and C5 (diagnostics), plus C3 (standardize
core). Remaining before E1: **C3 → C4**, **C5**.

## Phase 2 — postpro standardize-units core (C3): rules_setup + engine — ✅ (2026-07-23)

`postpro/standardize_units/{rules_setup,engine}.py` (`24-rules-setup.R` + `24-standardize-engine.R`)
— the HIGH-risk affine unit-conversion core (parity risk #9).

- **`rules_setup.py`** — `normalize_conversion_rule_columns` (legacy-header aliasing; reject two
  aliases → one canonical column), `validate_rule_schema`, `validate_conversion_rules`
  (normalized-key dedupe incl. case variants, finite factor/offset, chained-rule self-join guard
  excluding `all commodity`), and `prepare_standardize_rules` (materialize `unit_factor_num` /
  `unit_offset_num` + normalized `commodity_match_key` / `unit_source_key`). The xlsx multi-sheet
  rule readers are the orchestration IO boundary → deferred to C4.
- **`engine.py`** — `apply_standardize_rules` → `StandardizeResult(data, matched_count,
  unmatched_count, matched_rule_counts)`, in order **fold → revert-probe → two-stage match →
  affine convert**:
  - **multiplier fold** (regex `Patterns.standardize_multiplier_prefix`): `"1000 head"` value 5 →
    5000 unit `head`; comma thousands stripped; applied only for a finite prefix ≠ 1;
  - **revert-probe**: a folded row reverts to its original prefixed unit only when a rule matches
    that original form (specific, else `all commodity`) — else its base unit is kept so a
    base/fallback rule applies (the "not stranded" / "revert-to-all-commodity" cases);
  - **two-stage match** (specific commodity → `all commodity` fallback) then affine convert
    (`value * factor + offset`), rewriting the unit to the target; non-numeric non-blank values
    abort.
- **Parity:** new `standardize` `CaptureSpec` + one rich fixture (specific prefixed rule + kg
  fallback + celsius→fahrenheit offset + comma-thousands fold + an unmatched row).
  `test_standardize_parity` matches R on the converted value/unit, matched/unmatched counts, and
  the sorted `matched_rule_counts` (affected rows + effective multiplier). Unit suite
  `tests/postpro/test_standardize_units.py` mirrors the R testthat cases (conversion, offset,
  fallback + attribution, prefix priority, not-stranded, revert, all validation guards).

**Gates:** ruff + ruff-format + mypy strict clean (117 files) · **508 tests pass** (+25: 23 unit +
2 parity). **Track C: audit + utilities + standardize core done.** Remaining before E1 (postpro
runner): **C4** (standardize aggregation + orchestration incl. the xlsx rule readers) and **C5**
(diagnostics).

## Phase 2 — postpro standardize aggregation + orchestration (C4) — ✅ (2026-07-23)

`postpro/standardize_units/{aggregation,orchestration}.py` (`24-standardize-aggregation.R` +
`24-standardize-orchestration.R`) — completes the standardize-units stage (also picks up the xlsx
rule readers deferred from C3).

- **`aggregation.py`** — `aggregate_standardized_rows` (collapse rows identical on every column
  except the measure by summing it; all-null group → null; unique rows kept ahead of aggregated
  groups; column order/schema preserved; idempotent) + `extract_aggregated_rows`. Duplicate-group
  mask via `pl.struct(group_cols).is_duplicated()`.
- **`orchestration.py`** — the deferred xlsx rule readers (`ensure_standardize_template_exists`,
  `read_standardize_rule_workbook` [excludes `master_unit`], `read_all_standardize_rule_files`,
  `load_units_standardization_rules`); `build_standardize_layer_audit` (merge prepared rules with
  the engine's `matched_rule_counts`, attributing an `all commodity` rule to each applied
  commodity); `attach_standardize_diagnostics` → `StandardizeDiagnostics`; and
  `run_standardize_units_layer_batch` → typed `StandardizeLayerResult` (data + diagnostics + audit
  + layer_rules + matched_rule_counts + aggregated_source_rows; R used data.table attributes).
- **Parity:** new `standardize_agg` `CaptureSpec` + fixture. `test_standardize_agg_parity` matches
  R on `aggregate_standardized_rows` (dup sum + all-NA→null + unique kept) and
  `build_standardize_layer_audit` (commodity/affected/effective/target, all-commodity attribution).
  Unit suite `tests/postpro/test_standardize_agg.py` mirrors the R testthat cases (aggregation
  variants, extract, audit, diagnostics, readers, end-to-end run).

**Gates:** ruff + ruff-format + mypy strict clean (121 files) · **530 tests pass** (+22: 20 unit +
2 parity). **Track C complete: audit + utilities + standardize (core + agg/orchestration) done;
diagnostics (C5) remains.** E1 (postpro 9-step runner) now needs only **C5**.

## Phase 2 — postpro diagnostics (C5) — ✅ (2026-07-23)

`postpro/diagnostics/{preflight,rule_summaries,standardize_summaries,output}.py` (`25-preflight.R`
+ `25-rule-summaries.R` + `25-standardize-summaries.R` + `25-diagnostics-output.R`) — **completes
Track C (postpro non-engine).**

- **`preflight.py`** — `collect_postpro_preflight` (rule-dir existence, clean/harmonize file-naming
  patterns, expected dataset columns) → `PreflightResult`; `assert_postpro_preflight` raises
  `WhepError` on failure.
- **`rule_summaries.py`** — `summarize_stage_rules` (value_source/target filled from the `*_result`
  columns; affected NA→0; nulls-last sort), `build_stage_rule_catalog_from_payloads`, and
  `build_unmatched_rule_summary`. Shared `_anti_join_null_safe` folds null keys to a sentinel
  before anti-joining — **R data.table joins match NA↔NA but polars joins do not** (parity risk).
- **`standardize_summaries.py`** — `build_standardize_rule_catalog`, `summarize_standardize_rules`,
  and `build_unmatched_standardize_rule_summary` with the normalized-key counts branch (an
  `all commodity` rule matched via counts leaves the specific rule reported unmatched).
- **`output.py`** — `build_postpro_diagnostics` (three stage summaries),
  `build_last_rule_wins_overwrite_subset` (group-by 1-based row_id → collapse columns/files/stages
  → join final-stage values), and `persist_postpro_audit` → multi-sheet xlsx per stage
  (`matched_rules` + `unmatched_rules`) + the overwrite workbook, via openpyxl.
- **Parity:** new `diagnostics` `CaptureSpec` (16 exports) + `diagnostics_inputs.json` fixture.
  `test_diagnostics_parity.py` matches R on clean summarize + unmatched anti-join and standardize
  summarize + unmatched counts branch. Unit suite `tests/postpro/test_diagnostics.py` mirrors the R
  testthat cases (preflight naming/columns/assert, summaries, catalogs, overwrite subset, and
  `persist_postpro_audit` writing files + sheets).

**Gates:** ruff + ruff-format + mypy strict clean (127 files) · **544 tests pass** (+14: 12 unit +
2 parity). **Track C (postpro non-engine) COMPLETE.** E1 (postpro 9-step runner) is now unblocked
(B6 ✓, C1 ✓, C2 ✓, C4 ✓, C5 ✓).

## Track C completion audit — ✅ (2026-07-23)

Comprehensive gap analysis of everything up to and including Track C against the roadmap,
`session-prompts.md`, and `codebase-map.md`. Verified (not by status flags alone): **all 27
postpro R modules + all Stage-1 modules ported**; no scaffold remnants in any Track A/B/C module
(the only `StageNotImplementedError`s are E1 postpro-runner + Track D export, both correctly
out of scope); every done module has unit + parity coverage; **104 parity tests pass against 19
committed goldens** (real, not skipping). Two gaps found and closed, plus doc drift:

- **DB1 (CI, PR #10):** the `quality` workflow hung to its 6h timeout on every run while passing
  locally. Root cause was a real latent bug in Track A `ingest/transform/processing.py` — a
  default-`fork` `ProcessPoolExecutor` deadlocking against polars' Rayon thread pool on Linux.
  Fixed by pinning a `spawn` context (+ `timeout-minutes: 20` backstop). **CI now green in ~20s**
  across Python 3.11/3.12/3.13 — the first successful CI run in the project.
- **DB2 (Track C / C2, PR #11):** `read_rule_table`'s `.csv` branch kept the literal `"NA"` as a
  string, diverging from R `readr` (`na = c("", "NA")`). Fixed with `null_values=("", "NA")`;
  added a committed CSV fixture, an R golden (`rule_table_csv` CaptureSpec), a parity test, and a
  unit test. The deferred-bugs list is now **empty**.
- **Docs:** codebase-map Stage 2 header (`[scaffold]` → modules done / runner pending E1);
  migration-roadmap Phases 1–3 marked ✅ DONE.

**Result:** Tracks A, B, C are **100% complete** (modules + tests + parity + local gates + green
CI). Only Track D (export) and integration (E1 → E2 → E3) remain. Full suite **546 tests pass**.

## Track D — export / processed_data — ✅ (2026-07-23)

Ported `r/3-export_pipeline/30-processed_data/` (Track D, first slice):

- `processed_data/layers.py` <- `02-collect-layer-tables.R`: `collect_layer_tables_for_export`
  takes an explicit `{name: frame}` mapping (no global-env scan — the typed-results divergence),
  keeps names ending in `_raw/_clean/_normalize/_harmonize`, excludes `_wide_raw` and
  `_post_processed`, returns them sorted by name.
- `processed_data/export.py` <- `01/03/04`: `build_processed_export_path`
  (`normalize_filename(name) + ".tsv"` under `config.paths.data.export.processed`),
  `write_processed_table` (the `fwrite` analogue), and `export_processed_data`
  (harmonize-only by default via `config.export_config.export_layers`).

**The real risk was `fwrite` byte-parity**, not the detection logic. Empirically nailed down
(R 4.6.0) that `data.table::fwrite(sep="\t")` diverges from polars `write_csv(separator="\t")`
in exactly two ways, both handled so the output is byte-identical:

- **eol.** `fwrite` uses the platform newline (`\r\n` Windows / `\n` unix, per
  `.Platform$OS.type`); polars defaults to `\n`. `_FWRITE_EOL` mirrors `fwrite`, so the golden
  (captured from R on the same platform) and the port agree on every platform.
- **float formatting.** The exported `value` is `Float64` (audit `parse_double`). `fwrite`
  renders a double **identically to R `as.character()`** (verified 254-value battery) under the
  pipeline's `scipen=999`: 15 significant figures, fixed notation, trailing `.0` dropped
  (`1.0`->`1`, `1000.0`->`1000`, `1e16`->`10000000000000000`) — whereas polars keeps `1.0` and
  goes scientific at 1e16. `_format_double_r` (Decimal, prec=15, ROUND_HALF_EVEN) reproduces it;
  float columns are stringified before the write. For the finite decimals the pipeline actually
  produces (parsed inputs × exact unit factors) this is byte-identical to `fwrite`; `fwrite` and
  `as.character` only ever differ in the 15th digit for *arbitrary* ≥16-sig-fig doubles (raw
  `runif`-style), which the pipeline never generates (no division introduced).

Golden = the **whole TSV as a hex string** (`export_processed_data` CaptureSpec runs the real
`write_processed_table_fast`), so the parity test asserts exact bytes — pinning eol, auto-quoting
(embedded tab/newline/quote, empty-`""` vs NA), UTF-8, and the float format. Committed fixture
`synthetic/export_processed_inputs.json`.

**Gates:** ruff clean · mypy strict clean (131 files) · **580 tests pass** (was 546; +33 unit in
`tests/export/test_processed_data.py`, +1 parity) · 106 parity across 21 golden modules.
**Remaining Track D:** `lists/` (`31-lists`) + export runner wiring (E3).

## Track D — export / lists + runner — ✅ (2026-07-23)

Ported `r/3-export_pipeline/31-lists/` and **wired the export runner** — Stage 3 is now
module-complete (reachable end-to-end once the postpro runner E1 lands):

- `lists/unique_values.py` (`01` + `02`): `LISTS_SHEET_ORDER`, `infer_layer_sheet_name`,
  `compute_unique_column_values` (drop-null, code-point sort, `(blank)` prepended if any NA;
  float columns rendered via `format_double_r`), `build_column_lists_export_path`
  (`unique_<col>.xlsx` — the dead `list_suffix` constant is not used), `build_layer_tables_by_sheet`
  (union multiple objects per sheet via `concat(how="diagonal")`), `collect_union_columns`.
- `lists/merge.py` (`03`): `resolve_lists_export_columns` (config-order ∩ union), and
  `resolve_list_sheet_payloads` — the identical-layer merge (equal value-sets share one sheet,
  e.g. `raw_clean_normalize_harmonize`) with fixed discovery order. R compared normalized
  data.tables; the port compares the already-deterministically-sorted value lists (same result).
- `lists/write.py` (`04`): `build_column_unique_cache`, `write_column_lists_workbook`
  (no-header, one-value-per-row multi-sheet `xlsxwriter` write == `writexl(col_names=FALSE)`),
  `export_lists` (union → resolve → cache → **filename-collision guard** → sequential write).
  Parallelism not ported (R only parallelizes under a non-default `future` plan; pipeline default
  is sequential).
- `export/runner.py`: `run_export_pipeline(config, result, *, raw=None, overwrite=True)` builds the
  canonical `whep_data_{raw,clean,normalize,harmonize}` mapping (raw = `import_result.data`, passed
  by `run_pipeline`; the other three from `PostproResult`), ensures the export dirs, writes both
  families, returns a contract-checked `ExportResult`. `StageNotImplementedError` removed; the stale
  `test_export_stage_pending` contract test deleted.

**Parity strategy (xlsx can't be byte-compared).** The golden captures the *logical* layout as
atomic vectors: per-(layer, column) unique values (the sort/`(blank)` risk), the union + resolved
export columns, and per-column merged sheet names. Confirmed **polars `.sort()` == R
`sort(method="radix")`** on the un-normalized raw layer including accented values (`Åland` sorts
after ASCII — code point == C-locale == UTF-8 byte order), so risk #7 needs no override. The parity
test also runs the real `export_lists`, reads the workbooks back with openpyxl, and asserts sheet
names + cell values match. Committed fixture `export_lists_inputs.json`.

**Refactor:** promoted the R `as.character`/`fwrite` double formatter to
`setup/helpers/numeric.format_double_r` (now shared by the TSV writer and the lists numeric
branch); `processed_data/export.py` re-points to it (behavior unchanged).

**Gates:** ruff clean · mypy strict clean (137 files) · **634 tests pass** (+54: 36 unit + 19
parity, −1 stale) · 125 parity across 22 golden modules. **Track D complete.** Remaining: E1
(postpro runner) → E2/E3 integration wiring of `run_pipeline`.

## Baseline metrics (autocode)

| metric | value |
|--------|-------|
| tests  | 63 passed / 0 failed (100%) — 61 unit + 2 parity |
| ruff   | 0 issues |
| mypy   | 0 errors (48 files, strict) |
| perf   | n/a (enabled Phase 6) |

## Next

Per [migration-roadmap.md](docs/migration-roadmap.md). Ingest file_io (1a) is now done.
Continue the two parallel high-value tracks:

- **Ingest (Stage 1): DONE** — all modules ported, runner wired, stage-level parity green on
  the frozen corpus. `run_import_pipeline(config) -> ImportResult` is production-ready.
- **Next tracks (parallel):** (B) **Postpro rule engine** (Stage 2 critical path) — bottom-up
  `matching_strategy` → `matching_values` → `target_apply`; (C) **Postpro non-engine** — audit,
  standardize_units, diagnostics, utilities; (D) **Export** (Stage 3). Then Phase 5 wires
  `run_pipeline` end-to-end (ingest real data → postpro → export) with progress + parallelism.
- **Postpro rule engine (Stage 2 critical path):** bottom-up `matching_strategy` →
  `matching_values` → `target_apply`.

Use the `migrate-module` + `parity-check` skills. Add a `CaptureSpec` to
`tests/parity/registry.py` per new module; reuse `tests/fixtures/corpus/` as the raw root for
ingest captures (the file_metadata capture already reads corpus-relative paths from it).
