# Session prompts

Ready-to-paste kickoff prompts — **one per session** — for executing the
[migration-roadmap](migration-roadmap.md). Each is standalone: `CLAUDE.md` auto-loads the
project context, so a fresh session only needs the prompt below.

## How to use

0. **Ensure the session can read the R source repo.** Every prompt reads the R module it
   ports, which lives in the **sibling** repo
   `C:/Users/Usuario/Nextcloud/whep_alvaro/digitalization/whep-digitalization/` (the source
   of truth). Open the session with **both** repos accessible (add the R repo as a working
   directory / allowed path). Ground truth for correctness is the R source + the parity test
   — the prompts are pointers, not full specs.
1. Open a fresh session **in the `whep-digitize` project** (`cd` into this repo).
2. Paste the prompt for the session you're doing. It drives the `migrate-module` /
   `parity-check` skills, which encode the full procedure (read R → implement → test →
   parity → gates → update docs).
3. One session = one prompt. Adjacent LOW-risk sessions can be merged if context allows;
   give any **HIGH**-risk module its own session.
4. Branch per session (`git checkout -b migrate/<id>`), small PR. The only shared files
   sessions touch are `codebase-map.md` (status flip) and `progress.md` — trivial merges.

## Ordering & parallelism

```
S0 (parity infra)  ──►  everything
   ├─ Track A (ingest):     A1 ‖ A2 ‖ A4 ‖ A6  →  A3(A2) → A5(A3,A4) → A7(A5,A6)
   ├─ Track B (rule engine):B1 ‖ B3  → B2(B1) → B4(B1,B2) ‖ B5(B1,B2) → B6(B3,B4,B5,C2)
   ├─ Track C (postpro):    C1 ‖ C2 ‖ C3 ‖ C5   → C4(C3)
   └─ Track D (export):     D1 ‖ D2
Integration: E1(B6,C1,C2,C4,C5) → E2(A7,E1,D2) → E3(E2)
```

`‖` = can run in parallel (independent). `X(Y)` = X needs Y first. **Tracks A and B are the
highest-value pair — run them concurrently.** Cross-track note: rule-engine session **B6
needs C2** (the payload cache/loaders live in postpro utilities).

---

## S0 — Parity infrastructure  *(do first; blocks all parity work)*

```
Set up the R↔Python parity infrastructure for the whep-digitize migration. Freeze a fixed
input corpus (a small representative subset of the R project's data/1-import raw workbooks
plus tiny synthetic fixtures covering edge cases: empty, accented/unicode, duplicates,
wildcard __ANY__, NA) under tests/fixtures/. Build the golden-capture flow per the
parity-check skill: a reusable, DELETE-AFTER-USE R harness pattern that runs an R function
via Rscript (C:/Program Files/R/R-4.6.0) and writes deterministic outputs to
tests/golden/<module>/. Document the frozen-corpus location and capture command in
.claude/progress.md. Do not migrate any module yet — just stand up the harness and prove it
round-trips one trivial R function (e.g. normalize_string) to a golden file that a polars
test can read. Commit both the fixtures and tests/golden (the goldens are the frozen R
reference; committing them is what lets CI enforce parity without an R install).
```

---

## Track A — Ingest (Stage 1)

### A1 — file_io (discovery + metadata)  *(prereq: S0)*
```
/migrate-module the ingest file_io modules: discovery.py (ports 10-discovery.R) and
metadata.py (ports 10-metadata.R) in whep_digitize/ingest/file_io/. Reuse
setup.helpers.tokens for the positional filename parsing (yearbook = token 2 + first
4-digit token; commodity = tokens 7+). Risk LOW/MEDIUM. Add parity tests on real WHEP
filenames from the frozen corpus.
```

### A2 — header normalization  *(prereq: S0; HIGH; parallel-ok with A1/A4/A6)*
```
/migrate-module whep_digitize/ingest/reading/header_normalization.py (ports
11-header-normalization.R). HIGH risk / parity-critical: reproduce the ordered regex chain
+ diacritic-strip transliteration + canonical/alias renames (country→polity) with the
collision guards, exactly. Normalization follows the POLICY (NFD diacritic strip), NOT R's ICU
`Latin-ASCII`: do not add character-specific overrides — pin behavior with policy tests,
especially on accented/unicode headers. See r-to-python-mapping.md.
```

### A3 — reading (read_utils + sheet_read + batching)  *(prereq: A2)*
```
/migrate-module the rest of whep_digitize/ingest/reading/: read_utils.py (11-read-utils.R),
sheet_read.py (11-sheet-read.R), batching.py (11-batching.R). Key semantics: read every
sheet all-as-text (pl.read_excel engine="calamine", infer_schema_length=0); tag variable :=
sheet name; keep rows where ANY base column is non-empty; worker resolution
("auto"→min(8,cpu-1)). Parity-test sheet reads against R goldens.
```

### A4 — transform (transform_utils + reshape)  *(prereq: S0; HIGH; parallel-ok with A2/A3)*
```
/migrate-module whep_digitize/ingest/transform/transform_utils.py (12-transform-utils.R) and
reshape.py (12-reshape.R). HIGH: identify_year_columns (name matches ^\d{4}(-\d{4})?$, not a
metadata col), key-field normalization, year-header cleanup + duplicate-collision guard, then
the wide→long melt via pl.DataFrame.unpivot. Verify unpivot drops EXACTLY the columns R's
melt did; recompute year columns explicitly (no attribute passing). Parity-test the long shape.
```

### A5 — transform processing (fused + parallelism)  *(prereq: A3, A4; HIGH)*
```
/migrate-module whep_digitize/ingest/transform/processing.py (12-processing.R): the fused
read+transform-per-batch path. Implement sequential first, then ProcessPoolExecutor
parallelism preserving DETERMINISTIC output order independent of worker count, with a
graceful sequential fallback. Parity-test: parallel output == sequential output == R golden.
```

### A6 — validate  *(prereq: S0; HIGH; parallel-ok with A1/A2/A4)*
```
/migrate-module whep_digitize/ingest/output/validate.py (13-validate.R):
validate_long_dt_by_document. HIGH: per-document row ids, first-appearance ordering, the
4-key stable sort, and VERBATIM error-string formats. Reproduce exactly (a consumer compares
the text). Parity-test error strings AND order against R goldens on multi-document fixtures.
```

### A7 — consolidate + ingest runner  *(prereq: A5, A6)*
```
/migrate-module whep_digitize/ingest/output/consolidate.py (13-output.R: pl.concat
how="diagonal" + canonical column reorder) and wire whep_digitize/ingest/runner.py to the
full contract (discover → fused read+transform → drop_na_value_rows → validate_by_document →
consolidate → sort → ImportResult). Remove StageNotImplementedError. STAGE-LEVEL parity:
run_import_pipeline output matches R on the frozen corpus.
```

---

## Track B — Rule engine (Stage 2, critical path)

### B1 — matching strategy + values  *(prereq: S0)*
```
/migrate-module whep_digitize/postpro/rule_engine/matching_strategy.py
(23-matching-strategy.R) and matching_values.py (23-matching-values.R). Reproduce exactly:
key encode/decode (NA→na_match_key "..NA_MATCH_KEY..", target NA→na_placeholder
"..NA_INTERNAL.."), tokenized ;-membership match with wildcard __ANY__, order-preserving
concat merge (existing-first dedupe), and the elementwise change count that drives
convergence. Parity-test tokenized matching + NA↔NA on unicode fixtures.
```

### B2 — target apply  *(prereq: B1; HIGH)*
```
/migrate-module whep_digitize/postpro/rule_engine/target_apply.py (23-target-apply.R):
apply_target_updates_with_strategy. HIGH: last_rule_wins = stable sort by order columns then
group-last, with the overwrite-event emitter (only when unique_candidate_count>1); plus
concatenate. Functional polars scatter (join-back + when/then), no in-place mutation.
Parity-test both strategies + overwrite events.
```

### B3 — schema validation  *(prereq: S0; parallel-ok with B1/B2)*
```
/migrate-module whep_digitize/postpro/rule_engine/schema_validation.py
(23-schema-validation.R): coerce_rule_schema (strip clean_/harmonize_ prefix, enforce the 6
canonical columns, value_source optional), validate_canonical_rules (duplicate-key +
target/source conflict checks, type-compat), build_conditional_rule_dictionary (code-point
ordering for portable last-rule-wins). Parity-test the dictionary grouping + conflict aborts.
```

### B4 — conditional group  *(prereq: B1, B2; HIGH)*
```
/migrate-module whep_digitize/postpro/rule_engine/conditional_group.py
(23-conditional-group.R): apply_conditional_rule_group. HIGH: cartesian keyed join on
source_key, target-condition match on the matched subset, source+target scatter, encoded-NA
audit join-back. Functional polars throughout. Parity-test the audit table + changed_columns
(source-only rewrite must not mark the target).
```

### B5 — footnote rules  *(prereq: B1, B2; HIGH — hardest single port)*
```
/migrate-module whep_digitize/postpro/rule_engine/footnote_rules.py (23-footnote-rules.R):
apply_footnote_rules. Hardest port: explode ; tokens → cartesian join on rules → resolve per
(row_id, footnote_index) with precedence remove > replace > original → reconstruct in index
order. Match R's NA/empty/precedence semantics exactly (change count vs a deep-copied
before-image). Heavy fixture coverage + parity test.
```

### B6 — payload application + clean/harmonize multi-pass  *(prereq: B3, B4, B5, C2)*
```
/migrate-module whep_digitize/postpro/rule_engine/payload_application.py
(23-payload-application.R) and whep_digitize/postpro/clean_harmonize/* (22-*): the multi-pass
driver run_rule_stage_layer_batch. Loop passes (max 10), apply all payloads each pass, stop
on changed_value_count==0 (converged), repeated state (cycle → warn/abort per policy), or max
passes; normalization on pass 1 only. Replace R serialize() cycle detection with a
deterministic content hash (df.hash_rows() folded), keeping the fingerprint-screens →
exact-confirm design. Needs the payload loaders from postpro.utilities (C2). Parity-test
clean + harmonize convergence on rule fixtures.
```

---

## Track C — Postpro non-engine

### C1 — audit  *(prereq: S0)*
```
/migrate-module whep_digitize/postpro/audit/* (20-*): audit_data_output. Parse value →
Float64 (cast strict=False) but KEEP invalid rows in the output; reproduce the R divergence
where the audit regex ^[0-9]+(\.[0-9]+)?$ is stricter than the float parser (-3.5 flagged yet
parsed). Styled invalid-cell Excel highlight via openpyxl. Parity-test the audited frame +
findings.
```

### C2 — utilities  *(prereq: S0)  [needed by B6]*
```
/migrate-module whep_digitize/postpro/utilities/* (21-*): output_roots, diagnostics
(build_layer_diagnostics → LayerDiagnostics), templates (read_rule_table all-as-text with the
sheet schema-matching heuristic), payload_cache (2-level; off by default — port the md5
cache-key/build logic, back with dict + parquet, stub disk if needed). Parity-test rule-file
loading.
```

### C3 — standardize units core  *(prereq: S0; HIGH)*
```
/migrate-module whep_digitize/postpro/standardize_units/rules_setup.py (24-rules-setup.R) and
engine.py (24-standardize-engine.R). HIGH engine: leading numeric multiplier fold ("1000
head", value 5 → 5000, unit "head"; strip comma thousands), then two-stage match
(specific → "all commodity" fallback), then affine convert (value*factor+offset). Order:
fold → revert-probe → match → convert. Contract: (data, matched_count, unmatched_count,
matched_rule_counts). Parity-test conversions + the multiplier fold.
```

### C4 — standardize aggregation + orchestration  *(prereq: C3)*
```
/migrate-module whep_digitize/postpro/standardize_units/aggregation.py
(24-standardize-aggregation.R) and orchestration.py (24-standardize-orchestration.R): sum the
measure over duplicate groups (all-NA group → NA), order/schema-preserving and idempotent;
then run_standardize_units_layer_batch + the audit merge. Parity-test aggregation + the layer
audit.
```

### C5 — diagnostics  *(prereq: S0)*
```
/migrate-module whep_digitize/postpro/diagnostics/* (25-*): preflight checks, persist audit
workbooks (overwrite subset = group-by row + join; multi-sheet xlsx), clean/harmonize +
standardize matched/unmatched summaries (anti-joins; standardize has a normalized-key counts
branch). Parity-test the summary tables against R goldens.
```

---

## Track D — Export (Stage 3)

### D1 — processed data (TSV)  *(prereq: S0)*
```
/migrate-module whep_digitize/export/processed_data/* (30-*): collect_layer_tables_for_export
(detect _raw/_clean/_normalize/_harmonize; exclude _wide_raw and _post_processed), filter to
export_layers (default harmonize), write {stem}.tsv via pl.DataFrame.write_csv(separator="\t").
Parity-test the written TSV bytes vs R.
```

### D2 — lists (xlsx) + export runner  *(prereq: S0)*
```
/migrate-module whep_digitize/export/lists/* (31-*) and wire whep_digitize/export/runner.py.
Per-column unique_<col>.xlsx: per-(layer,column) unique values (drop NA, code-point sort,
prepend "(blank)" if any NA); identical-layer merging into one sheet
(e.g. raw_clean_normalize_harmonize); fixed sheet order; filename-collision guard. Runner
returns ExportResult; assert_export_paths_contract. Remove StageNotImplementedError.
Parity-test workbooks + sheet layout.
```

---

## Integration (Phase 5–6)

### E1 — postpro runner (9-step)  *(prereq: B6, C1, C2, C4, C5)*
```
Wire whep_digitize/postpro/runner.py to the full 9-step orchestration: audit → init →
templates → preflight-collect → preflight-assert → clean → standardize → harmonize →
persist, returning PostproResult (harmonize/clean/normalize + typed diagnostics). Remove
StageNotImplementedError. STAGE-LEVEL parity: run_postpro_pipeline output matches R on the
frozen corpus (including multi-pass pass counts).
```

### E2 — end-to-end orchestration + parallelism + progress + e2e parity  *(prereq: A7, E1, D2)*
```
Wire run_pipeline through all four real stages. Add rich.progress bars to each stage runner
(gated by RuntimeOptions.progress_enabled). Ensure ProcessPoolExecutor parallelism in ingest
and list export preserves deterministic order. Then run the FULL R pipeline and the Python
pipeline on the frozen dataset and diff processed TSVs + unique-list workbooks to ZERO
differences. Fix any divergence to reach byte-identical output.
```

### E3 — performance + CI + docs finalize  *(prereq: E2)*
```
Add .claude/bench/bench.py (full-pipeline wall-clock on the frozen dataset, prints
"PIPELINE_SECONDS: <n>"), enable the performance metric in autocode.toml and re-normalize
weights. Profile hot paths (postpro rule engine first) and optimize per the performance
guideline. Harden CI (coverage gate). Refresh uv.lock. Finalize docs (flip remaining
[scaffold] rows to [done], retire scaffolding notes). Then the migration is DONE — verify the
definition-of-done in migration-roadmap.md.
```

---

## Deferred bugs

Bugs found but **intentionally not fixed** in the session that found them. Adding an entry here
when a bug is deferred is **mandatory** (see `CLAUDE.md` → *Log deferred bugs*). Each entry states
the bug, its impact, why it was deferred, known risks, and when to revisit, plus a paste-able fix
prompt. **Remove an entry only when the bug is fixed.** Intentional R-divergences that cannot
change pipeline output are documented inline / in `progress.md`, not here.

**The list is currently empty.** (DB1 — CI fork deadlock — fixed in PR #10, 2026-07-23. DB2 —
`read_rule_table` CSV parity — fixed in PR #11, 2026-07-23. DB3 — unit-conversion float
divergence on 3 rows — fixed 2026-07-31: root cause was **not** the conversion arithmetic but
calamine's lossy float→text coercion in `ingest/reading/sheet_read.py`; see
[full-dataset-parity.md](full-dataset-parity.md) and the progress-log entry.)

*Regenerate/adjust this list from [migration-roadmap.md](migration-roadmap.md) if the plan
changes. Flip each module's [codebase-map.md](codebase-map.md) status and append a
[progress.md](../progress.md) line as sessions complete.*
