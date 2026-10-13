# Pipeline behaviors

The **intentional** behaviors of the pipeline — the ones that look like bugs, or that a
reasonable person would "clean up" and thereby change the data. Every entry here is deliberate
and pinned by tests. **Read this before changing pipeline semantics.**

Companion docs: [architecture.md](architecture.md) (stages, data flow),
[codebase-map.md](codebase-map.md) (where things live),
[constants-and-options.md](constants-and-options.md) (tunables).

---

## String normalization policy

`setup.helpers.strings` folds text to lowercase ASCII: **NFD decomposition, drop combining
marks, lowercase**, then replace runs of characters that are neither alphanumeric nor **retained
punctuation** with a single space, and trim.

- **The retained punctuation set is exactly `; , : ( ) [ ]`** — the same for every column,
  footnotes included. There is exactly **one** normalizer: `normalize_text` (scalar) and
  `normalize_string` (column). The former `clean_footnote` / `clean_footnote_column` pair was a
  duplicate of it and has been removed.
- Every other symbol is replaced, including ones that were previously kept in footnotes:
  `.`, `/`, `*`, `-`, `#`, `%`, `'`. So `incl. burma` → `incl burma` and
  `sodium fluosilicate, 98 %` → `sodium fluosilicate, 98`.
- Runs collapse to a **single** space, so a stripped symbol next to a space does not produce a
  double space.
- Accented Latin letters fold to their base: `café` → `cafe`, `ñ` → `n`.
- A character with **no canonical ASCII base** is *not* expanded — it is simply dropped by the
  replacement step. So `ø`, `ß`, `æ`, `œ`, ligatures, superscripts and symbols (`®`, `½`,
  `±`) disappear rather than becoming `o`, `ss`, `ae`, `oe`, `(R)`, `1/2`.
- **No character-specific exceptions exist, by design.** Do not add any: match keys route
  through this one implementation, so a special case here silently changes which rules fire.

Because `;` is retained, it survives into match keys — and target-condition matching is now
tokenized for **every** column, so those `;` are token separators everywhere. See the rule-engine
section for the `#EXACT#` directive that opts a rule out.

One visible consequence: the `(unknown_commodity)` placeholder normalizes to
`(unknown commodity)` — the parentheses are retained, the underscore is not.

Pinned by policy tests in `tests/setup/test_helpers.py`.

## Import

- Every sheet is read **all-as-text**; each column stays a string through import. The single
  downstream exception is `value`, parsed to `Float64` in the audit step.
- **Float text precision is repaired.** The reader's own text coercion rounds a stored double to
  about 12 significant digits, so a cell holding `0.09999999999999964` would arrive as `"0.1"`
  and a later ×1000 unit conversion would yield `100` instead of `99.9999999999996`. Each sheet
  is therefore read twice — once all-as-text, once dtype-inferred — and only cells that do not
  round-trip to the exact stored number are rewritten. *Residual limitation:* a column mixing
  text and numbers infers as `String`, so its numeric cells keep the rounded text.
- The `country` header is renamed to the canonical `polity`.
- **`iso_whep`** sits between `continent` and `polity` in the canonical order (and so in the row
  sort, ahead of `polity`). No source workbook carries it, so ingest **creates it once**, during
  consolidation, on the combined raw frame: every row gets `"iso-" + year` (`iso-1937`,
  `iso-1934-1939`; a null `year` gives a null seed). The prefix is
  `defaults.iso_whep_year_prefix`. That is the only time code writes the column: every later
  change comes from clean/harmonize rule files (e.g. `polity_iso` turning `iso-1937` into a
  code). The seed is unconditional, so a sheet that did carry `iso_whep` would be overwritten.
  Its values are *not* normalized at ingest (`variable`/`hemisphere`/`continent`/`polity` are;
  normalization would lowercase an ISO code and replace any `-` in it with a space), and it is
  not an audit column.
- **Row order follows the seed.** Because `iso_whep` is a sort key ahead of `polity`, rows in
  `raw`/`clean`/`normalize` are ordered continent → year tag → polity → …, and in `harmonize`
  (once rules have written codes) continent → code → polity → …. The frozen ingest golden
  predates the column, so `test_import_stage_parity.py` compares values in the golden's key order
  (the current key without `iso_whep`) and pins the new order in a separate test.
- Each **sheet name becomes the `variable` value** (one variable per sheet).
- Year columns are those matching `^\d{4}(-\d{4})?$`; a duplicate after year-header cleanup is a
  fatal error, not a silent merge.
- `unit` is intentionally left **raw** — only the four key columns are normalized.
- Rows null in `value` are dropped by default (`RuntimeOptions.drop_na_values`).
- **`file`** (formerly `document`) is the provenance column: the name of the source workbook,
  written for every row by `add_metadata` during the per-file transform. Validation groups rows
  by it.
- Validation error strings and their ordering are a **contract**: per-file row ids,
  first-appearance file ordering, and a 4-key stable sort. Consumers compare the text. The
  duplicate-entry message lists each key column as `<column> = <value>`, so it now ends
  `..., file = <workbook>`. The mandatory-value message keeps its fixed wording
  (`missing mandatory value in document '<workbook>', row_id ..., column ...`): that "document"
  is prose, not the column name, and the frozen goldens pin the text byte for byte.
  Parity tests translate the old column name at the boundary (`tests/parity/goldens.py`).

## Audit

Two deliberate behaviors — **do not "fix" either**:

1. Rows failing validation are **kept** in the audited output. The result is the full dataset
   with `value` parsed, not the invalid subset removed.
2. The audit regex `^[0-9]+(\.[0-9]+)?$` is **stricter than the float parser**. A value like
   `"-3.5"` is therefore flagged as a finding *and still parses* to `-3.5`. Negative and
   scientific notation are reported yet retained.

## Rule engine

- Two sentinel tokens are load-bearing and must stay byte-exact: null match keys collapse to
  `"..NA_MATCH_KEY.."`, and null target results ride through joins as `"..NA_INTERNAL.."`.
  Null matches null only because both sides collapse to the former.
- **Matching is element-wise for every column, on both sides.** The **source** cell is exploded on
  `;` and each rule is evaluated against a single token; a matching token is substituted **in
  place**, leaving its siblings intact, and the cell is rebuilt deduplicated and sorted. So
  `hemisphere = "a; b; c; d"` with a rule `a` → `z` yields `b; c; d; z`, not `z`.
- **Target-condition matching is likewise tokenized.** The current value is split on `;` and the
  condition matches on **token membership**; a full-string match always also counts. There is no
  per-column opt-in — `africa` matches a `continent` of `africa; america; asia`.
- **Rule cells are canonicalized on load.** Every string cell of a rule file is split on `;`,
  trimmed, deduplicated, sorted, and rejoined as it is read, so `"c; a; b; a"` becomes `"a; b; c"`.
  This happens strictly **within one cell** — tokens are never mixed across cells, rows, or
  columns. An `#EXACT#` prefix is split off first and re-attached, since sorting it with the
  tokens would move it out of the leading position and stop it being recognised.
- **Token subsetting is not supported, by design.** A rule value is either a single token (default)
  or an exact full cell (`#EXACT#`). A multi-token rule value without `#EXACT#` matches nothing,
  because it is keyed whole and is not one of the cell's tokens.
- **`#EXACT#` opts a single rule out.** Prefixing a target-condition value with `#EXACT#`
  (constant `postpro.rule_match_exact_token`) forces full-string matching for that rule: no token
  membership, and no wildcard interpretation — which is how a literal `#ANY#` is matched. The
  marker is a rule-authoring directive, not data, and is stripped before keying.
- **Both markers are case-insensitive and whitespace-tolerant**, because rule files are typed by
  hand and a case slip would otherwise leave the marker in the value and silently stop the rule
  from ever matching. `#EXACT#africa`, `#EXACT# africa` and `  #exact#   africa  ` are all
  equivalent; likewise `#ANY#` / `#any#`.
- `#ANY#` is the explicit wildcard, honoured on **every** column (previously only the tokenized
  ones), unless suppressed by `#EXACT#`.
- `#REPLACE#` is the unconditional full-cell overwrite (D12). Like `#ANY#` it is the **whole**
  condition value, case-insensitive and whitespace-tolerant, and `#EXACT#` suppresses it
  (`#EXACT# #REPLACE#` matches the literal text).
- An **empty-string current value never matches** under tokenized matching — the token lookup
  cannot key it. Under `#EXACT#`, which is pure full-string equality, an empty condition *does*
  match an empty current value. Both are intentional.
- **Symmetric tokenized substitution.** Both source and target use the same
  token-by-token substitution model: the cell is split on `;`, each token is matched
  independently against rules, and the cell is rebuilt deduplicated and sorted.
  Substitution is by **token value** (not by index), so the result is independent of
  token order. The default strategy is `token_substitute`; the old cell-level
  `last_rule_wins` strategy was replaced by `first_rule_wins` via token substitution dict (D7).
- **D1 — Substitution by value.** Token substitutions are keyed by the matched token's
  value, not its position. This is equivalent to index-based substitution (tokens are
  unique after deduplication) but more robust against reordering.
- **D2 — `#EXACT#` rewrites the entire cell on its own side.** A rule with `#EXACT#` in
  `value_source_raw` causes a full-cell override on the **source** column only. A rule with
  `#EXACT#` in `value_target_raw` causes a full-cell override on the **target** column only.
  The two sides are independent: `#EXACT#` in the source condition does NOT affect how the
  target column is rewritten, and vice versa. Example: source `"a; b; c"` with rule
  `#EXACT# a; b; c` → `"X"` and target `"p; q"` with condition `"p"` → `"P"` yields source
  `"X"` and target `"P; q"` (source is full-cell override, target is token substitution).
- **D3 — `#ANY#` adds a token (does not replace).** A rule with `#ANY#` in the condition
  adds the rule's value as an additional token without replacing existing tokens. Both
  source and target. Example: target `"a; b; c"` with rule `#ANY#` → `"X"` yields
  `"X; a; b; c"` (sorted and deduplicated). If the token already exists, it is not
  duplicated.
- **D4 — `value_target_raw = None` matches only NA.** An empty cell in the rules file
  matches **only** when the current target value is `None`/NA. It is not a wildcard.
  The wildcard is `#ANY#`, not `None`. No changes from previous behavior.
- **D5 — Normal rule replaces the matching token.** A rule without directives replaces
  only the matching token, preserving siblings. Example: target `"a; b; c"` with rule
  `"b"` → `"B"` yields `"a; B; c"`.
- **D6 — Multi-token values expand.** When a rule's `value_source` or `value_target`
  contains `";"`, it is expanded into individual tokens during reconstruction by
  `canonicalize_token_cell`. In the next multi-pass iteration, the expanded tokens are
  independent. Example: source `"x; y"` with rule `"x"` → `"a; b; c"` yields
  `"a; b; c; y"` after reconstruction.
- **D7 — `first_rule_wins` via token substitution dict.** When multiple rules in the same
  `(column_source, column_target)` group match the same source token, the first rule in join
  order wins. This is enforced by the token substitution dict using first-write-wins semantics:
  when a token already has a pending substitution, subsequent substitutions for that token are
  skipped. Groups are NOT decomposed — all rules in a `(column_source, column_target)` pair
  are processed together in a single vectorized pass. Example: target `"a; b; c"` with two
  rules `"a"` → `"A"` and `"a"` → `"AA"` yields `"A; b; c"` (the first rule's substitution
  for token `"a"` is applied; the second rule's substitution for the same token is skipped).
  Two consequences, both deliberate:
  - **A losing rule's target token substitution is suppressed as well**, on *both* the
    `token_substitute` and the `concatenate` path. A rule whose source rewrite was skipped must
    not silently apply its target token removals or merges. Rules that never competed on the
    source side (`source_value_column_present` false — target-only rules) are never losers and
    are never suppressed.
  - **A full-cell override is exempt from that suppression.** An `#EXACT#` rule that loses the
    source cell still applies its own target rewrite: the two address different columns, so
    losing one does not invalidate the other. Example: `commodity` `"a; b"` with
    `#EXACT# a; b` → `"FIRST"` (target `"p"` → `"P"`) and `#EXACT# a; b` → `"SECOND"`
    (target `"q"` → `"Q"`) yields commodity `"FIRST"` and target `"P; Q"`.
- **D9 — No overwrite-event diagnostics.** Token-level collisions are resolved silently by
  D7 (first-write-wins in token substitution dict); nothing records them. There is no overwrite-event frame and no
  `matched_token` field anywhere in the engine — `ConditionalGroupResult` carries only `data`,
  `audit`, `changed_value_count` and `changed_columns`. The per-rule `audit` frame, which
  records one row per applied rule, is the only diagnostic surface for rule application.
- **D10 — `value_source_raw = None` matches only NA.** Symmetric to D4 on the source side: an
  empty source cell in the rules file matches **only** when the current source value is
  `None`/NA. It is not a wildcard (`#ANY#` is). A NULL source condition is inherently a
  full-cell condition — the only thing it can mean is "this cell is NA" — so it is flagged
  exact and joins the full-cell candidate, never a token; `encode_rule_match_key` folds both
  sides' nulls to the NA sentinel, so it matches NA cells and only NA cells. This enables rules
  shaped "when `continent` IS NULL and `footnotes` contains X → fill `continent`, clear
  `footnotes`", which silently never fired before 2026-09-05.
- **D11 — A full-cell override outranks token substitution, regardless of rule order.** When
  one rule produces a full-cell override for a row (`#EXACT#`, or a `None`-matches-NA
  condition) and another rule in the same group substitutes a token in that same row, the
  full-cell override wins and the token rule is discarded — even when the token rule comes
  later in rule order. D7's first-write-wins governs collisions on *the same token*;
  an `#EXACT#` rule addresses the whole cell, not a token, so the two never compete for the
  same slot. The precedence is deterministic and applies identically on the source and target
  sides. When two *full-cell* rules compete for the same cell they do address the same slot, so
  D7 arbitrates: the **first** in join order claims it, and a first override of `None` (delete
  the cell) is not replaced by a later one. Example: cell `"a; b"` with rules `#EXACT# a; b` →
  `"P"` and `"a"` → `"Q"` yields
  `"P"` in either rule order. Authoring both is contradictory; the engine does not warn.
- **D12 — `#REPLACE#` overwrites the whole cell, whatever it holds, with no rule-order
  tie-break.** As a condition value it matches **any** current cell — null, empty, single- or
  multi-token — and the cell becomes the rule's result. Typical use, in `value_target_raw`:
  `polity, british aden, british aden, iso_whep, #REPLACE#, adc-1937-1967` sets `iso_whep` to
  `adc-1937-1967` on every `british aden` row, independent of its current value (a blank
  condition would only fill an empty cell, D4; `#ANY#` would add a token, D3; `#EXACT#` needs the
  old value). Rules:
  - **Outranks every other rewrite of that cell** in the same group (token, `#EXACT#`, `#ANY#`,
    `None`-matches-NA), in either rule order.
  - **No tie-break.** Every `#REPLACE#` rule that matches a cell contributes, and the cell is the
    canonical **union** of their results (split, deduplicated, sorted). Rule order therefore
    never changes the outcome: a `british aden; yemen` cell with one replace rule per polity
    gets `adc-1937-1967; yem-1990` either way. Two replace rules giving *one* polity different
    codes also produce both — that is a rule-file conflict, and it stays visible in the data
    instead of being silently resolved.
  - **Exempt from D7 suppression.** A `#REPLACE#` target still applies when its rule lost the
    source-token competition, on both the token and the `concatenate` paths.
  - An empty result clears the cell to null; an empty result alongside non-empty ones
    contributes nothing.
  - **Source side** (`value_source_raw = #REPLACE#`): the rule matches every row (the source
    condition is dropped, so only the target condition selects rows) and the whole source cell
    becomes the union of the matching replace rules' `value_source`.
  - **`concatenate` columns** (`notes`, `footnotes`): the cell is replaced, not appended to.
  - In multi-pass, a replace rule fires on every pass but changes nothing after the first, so it
    converges; two groups that rewrite the same cell differently can still oscillate, which the
    cycle detection reports.
- `concatenate` merges both sides into one canonical token set: deduplicated and **sorted**,
  like every other reconstruction path. This applies even when only one side is present.
- **`footnotes` has no special engine.** A footnote rule is just a rule whose source column is
  `footnotes`; it runs through the same element-wise path as every other column. A rule whose
  source result is missing **removes** the matched token and keeps its siblings. Where several
  rules hit the same token, the first in rule order wins via first-write-wins (D7) — there
  is no remove-over-replace precedence. The rebuilt cell is deduplicated and sorted rather
  than kept in original token order.
- A group whose only effect was a source rewrite marks the **source** column as changed, not the
  target.

## Multi-pass (clean / harmonize)

- Maximum **10 passes**; stop on zero changes (converged), on a repeated state (cycle → warn per
  policy), or on reaching the cap.
- Match-key normalization runs on **pass 1 only**.
- Cycle detection is two-tier: a cheap fingerprint (row count + per-column dtype, null count and
  byte length) screens candidates, and an exact folded content hash confirms. Convergence rests
  mainly on the cheap zero-change early stop; the hash is the safety net.

## Unit standardization

Strict order: **fold → revert-probe → two-stage match → affine convert**.

- **Leading-multiplier fold:** `"1000 head"` with value 5 becomes value 5000, unit `head`;
  comma thousands are stripped. Applied only for a finite prefix ≠ 1.
- **Revert-probe:** a folded row reverts to its original prefixed unit only when a rule matches
  that original form, so a base/fallback rule can still apply otherwise.
- **Two-stage match:** the specific commodity first, then the `#ALL#` fallback.
- **Affine convert:** `value * factor + offset`, rewriting the unit to the target.
- Aggregation sums the measure over duplicate groups; an **all-null group yields null**. It is
  order- and schema-preserving, and idempotent.

## Export

- **Processed TSV byte contract.** The record separator is the **platform newline** (`\r\n` on
  Windows, `\n` elsewhere). Float columns are stringified before the write so doubles render at
  **15 significant figures, fixed (never scientific) notation**, with trailing zeros and a bare
  trailing `.` removed (`1.0` → `1`, `1e16` → `10000000000000000`). Fields containing a tab,
  newline or quote are quoted, and empty string stays distinct from null. UTF-8.
- **Every layer is exported to its own TSV** — `whep_data_raw`, `_clean`, `_normalize`,
  `_harmonize` (`output_config.output_layers`). A configured layer with no table is skipped
  rather than an error, so `raw` is absent unless the ingest frame reached the export runner.
- **All-null columns are dropped per layer, immediately before export.** Every layer frame is
  passed through `drop_all_null_columns` (`setup/helpers/frames.py`) after canonicalization and
  before either export family reads it. "Empty" means every value is `null` — a column of
  nothing but empty strings is real data and is kept. This runs *after* postpro, not inside it:
  the frames `PostproResult` carries, the per-stage `logs` TSVs, and the duplicate audit all see
  the full, undropped column set; only the four exported layer tables are pruned.
  **The drop is independent per layer** — a column entirely null in `clean` but populated by a
  later rule in `harmonize` is dropped from `clean`'s TSV and kept in `harmonize`'s, so the four
  processed TSVs can legitimately have different headers. Both export families already tolerate
  this: `export_processed_data` writes each layer as its own file with no shared-schema
  assumption, and the unique-list machinery treats an absent column in one layer as contributing
  no values from that layer, not an error (`compute_unique_column_values` returns `[]` for a
  missing column; `resolve_lists_export_columns` only fails if a configured column is missing
  from *every* layer). A frame with zero rows, or one whose columns are *all* null, is left
  untouched rather than collapsed — see `drop_all_null_columns`'s docstring for why.
  Consequence for `notes` in `raw` (nothing populates it before postpro): it is absent from
  `whep_data_raw.tsv`; a layer gains the column, in canonical position, as soon as a rule
  fills it there. `iso_whep` is seeded at ingest, so it is present in every layer, `raw`
  included, and always has a `unique_iso_whep.xlsx`.
- Layer detection includes names ending `_raw`/`_clean`/`_normalize`/`_harmonize` and **excludes**
  `_wide_raw` and `_post_processed`.
- **Unique lists:** per (layer, column) unique values with nulls dropped, sorted by Unicode code
  point (equivalently UTF-8 byte order, so accented values sort after ASCII), and `"(blank)"`
  prepended when any null was present.
- Layers with identical value sets share one sheet (e.g. `raw_clean_normalize_harmonize`), in a
  fixed sheet order.
- The workbook `created` date is pinned so repeated runs are byte-reproducible.

## Duplicate audit

The last post-processing step writes one TSV per layer into `data/postpro/duplicates/`, named
`<layer>_dup.tsv` for `raw`, `clean`, `normalize` and `harmonize`.

- **Two criteria, two boolean columns.** `dup_full` — the row repeats across *every* column;
  `dup_excl_value` — the row repeats across every column *except* `value`. All occurrences of a
  repeated row are flagged, not just the second and later ones.
- **Only `dup_excl_value` rows are exported.** `dup_full` is a strict subset of it, so a row with
  `dup_excl_value` true and `dup_full` false is the interesting case: the same record carrying a
  conflicting `value`.
- **A file is always written**, even when a layer has no duplicates or is empty — header row
  only, preserving the source schema plus the two flags. "Audited, nothing found" therefore
  reads differently from "never ran".
- **Nulls compare equal** (polars grouping semantics), so rows jointly missing a field still
  count as duplicates.
- **`raw` means the canonicalized raw frame**, not the untouched ingest output: semicolon-token
  cells are canonicalized first, so rows differing only in token order compare equal.
- Row order is inherited from the source layer, which is already canonically sorted — the audit
  adds no ordering of its own and is deterministic.
- **Provenance columns dominate the key.** Every non-`value` column participates, including
  `file` (then named `document`) and `yearbook`. On the production dataset the audit finds
  nothing, because repeated records occur across *different* source workbooks rather than within
  one; they only appear once provenance columns are excluded too (measured 2026-09-17: 0
  excluding `value` alone, 1,029 also excluding `file`, 149,713 also excluding `yearbook`).

## Target tokenization

Source and target are now **symmetric**: both use token-by-token substitution by value.
The rule engine no longer distinguishes between source and target handling.

### Behavior by rule type

| Rule type | Condition in rules file | Source behavior | Target behavior |
|-----------|------------------------|-----------------|-----------------|
| Normal | `value_source_raw = "x"` / `value_target_raw = "x"` | Replaces matching token | Replaces matching token |
| Exact match (source) | `value_source_raw = "#EXACT# a; b"` | Replaces entire source cell | No effect on target |
| Exact match (target) | `value_target_raw = "#EXACT# a; b"` | No effect on source | Replaces entire target cell |
| Wildcard add | `value_source_raw = "#ANY#"` / `value_target_raw = "#ANY#"` | Adds token to cell | Adds token to cell |
| Replace (D12) | `value_source_raw = "#REPLACE#"` / `value_target_raw = "#REPLACE#"` | Matches every row; replaces entire source cell | Matches any cell; replaces entire target cell |
| None (empty) | `value_target_raw` is empty/NA | N/A | Matches only when current value is NA |

### Concrete examples

**Normal rule (token substitution):**
```
Cell: "a; b; c"
Rule: "b" → "B"
Result: "a; B; c"  (only "b" replaced; siblings preserved)
```

**Multiple rules, different tokens:**
```
Cell: "a; b; c"
Rule 1: "a" → "A"
Rule 2: "c" → "C"
Result: "A; b; C"  (each token substituted independently)
```

**Multiple rules, same token (first wins at token level):**
```
Cell: "a; b; c"
Rule 1: "a" → "A"
Rule 2: "a" → "AA"
Result: "A; b; c"  (Rule 1 wins for token "a" via first-write-wins)
```

**`#EXACT#` (full cell rewrite):**
```
Cell: "a; b; c"
Rule: "#EXACT# a; b; c" → "X"
Result: "X"  (entire cell replaced)
```

**`#ANY#` (add token):**
```
Cell: "a; b; c"
Rule: "#ANY#" → "X"
Result: "X; a; b; c"  (sorted, deduplicated; "X" added)
```

**`#REPLACE#` (overwrite, whatever the cell holds):**
```
Cell: "a; b; c"   (or "", or NA)
Rule: "#REPLACE#" → "X"
Result: "X"
Two matching replace rules → "X" and "Y": "X; Y" in either rule order
```

**Multi-token value expansion:**
```
Cell: "x; y"
Rule: "x" → "a; b; c"
Result: "a; b; c; y"  ("a; b; c" expanded into individual tokens)
```

**`None` condition (NA-only match):**
```
Cell: null/NA
Rule: value_target_raw = (empty) → "default"
Result: "default"  (applies only because cell is NA)

Cell: "existing"
Rule: value_target_raw = (empty) → "default"
Result: "existing"  (does NOT match; None is not a wildcard)
```

**`#EXACT#` in source only (independent sides):**
```
Source cell: "a; b; c"    Target cell: "x; y; z"
Rule: "#EXACT# a; b; c" → "REPLACED"  |  condition: "y" → "Y"
Result: source = "REPLACED"  target = "x; Y; z"
(Source is full-cell override; target is token substitution. Independent.)
```

## Determinism

Identical inputs + options must yield identical outputs.

- Sort through `sort_pipeline_stage_df`.
- Parallel stages preserve submission order, so output is independent of worker count; a broken
  worker pool falls back to sequential.
- Sorting is by Unicode code point everywhere — never locale-aware collation.
- Null keys are folded to a sentinel before anti-joins, because polars joins do **not** match
  null to null.

## Reference outputs (goldens)

`tests/golden/<module>/<export>.json` holds frozen expected output, asserted by
`tests/parity/`. These files are **committed and immutable**, and there is **no regeneration
path** — a golden changes only through a deliberate, reviewed edit, so a failing parity test
always means the pipeline's behavior changed. `tests/parity/test_goldens_present.py` fails
loudly if any golden is missing, because the individual tests skip when their golden is absent
and would otherwise pass while comparing nothing.

**Caveat on the stage-level goldens.** `import_stage` and `postpro_stage` pin the *output* of the
full stage sequence, so per-step behavior is genuinely verified — but the goldens were produced
from a reconstruction of the stage wiring. Step order and what feeds what are therefore verified
by **review**, not by execution. Re-review those two when you change a stage runner's wiring.
