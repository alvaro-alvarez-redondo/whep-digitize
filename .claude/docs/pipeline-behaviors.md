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
- Each **sheet name becomes the `variable` value** (one variable per sheet).
- Year columns are those matching `^\d{4}(-\d{4})?$`; a duplicate after year-header cleanup is a
  fatal error, not a silent merge.
- `unit` is intentionally left **raw** — only the four key columns are normalized.
- Rows null in `value` are dropped by default (`RuntimeOptions.drop_na_values`).
- Validation error strings and their ordering are a **contract**: per-document row ids,
  first-appearance document ordering, and a 4-key stable sort. Consumers compare the text.

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
- An **empty-string current value never matches** under tokenized matching — the token lookup
  cannot key it. Under `#EXACT#`, which is pure full-string equality, an empty condition *does*
  match an empty current value. Both are intentional.
- `last_rule_wins` = stable sort by the order columns, then take the **last** per group.
  Overwrite events are emitted **only** when a row received more than one *distinct* candidate.
  A null candidate renders as the literal string `"NA"` in `candidate_values`.
- `concatenate` merges both sides into one canonical token set: deduplicated and **sorted**,
  like every other reconstruction path. This applies even when only one side is present.
- **`footnotes` has no special engine.** A footnote rule is just a rule whose source column is
  `footnotes`; it runs through the same element-wise path as every other column. A rule whose
  source result is missing **removes** the matched token and keeps its siblings. Where several
  rules hit the same token the last in join order wins (there is no remove-over-replace
  precedence), and the rebuilt cell is deduplicated and sorted rather than kept in original
  token order.
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
- Layer detection includes names ending `_raw`/`_clean`/`_normalize`/`_harmonize` and **excludes**
  `_wide_raw` and `_post_processed`.
- **Unique lists:** per (layer, column) unique values with nulls dropped, sorted by Unicode code
  point (equivalently UTF-8 byte order, so accented values sort after ASCII), and `"(blank)"`
  prepended when any null was present.
- Layers with identical value sets share one sheet (e.g. `raw_clean_normalize_harmonize`), in a
  fixed sheet order.
- The workbook `created` date is pinned so repeated runs are byte-reproducible.

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
