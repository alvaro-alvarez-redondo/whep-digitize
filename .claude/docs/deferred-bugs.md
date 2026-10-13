# Deferred bugs

Bugs found but **intentionally not fixed** in the session that found them. Adding an entry here
when a bug is deferred is **mandatory** (see [CLAUDE.md](../../CLAUDE.md) → *Log deferred bugs*).

Each entry must state:

- **What** the bug is, precisely enough to reproduce.
- **Impact** — what breaks, and for whom.
- **Why it was deferred** in that session.
- **Known risks** of leaving it.
- **When to revisit** — the trigger or condition.
- A **ready-to-paste fix prompt**.

**Remove an entry only when the bug is fixed**, so unresolved issues stay visible and
actionable. Deliberate behaviors that cannot change output are not bugs — document those in
[pipeline-behaviors.md](pipeline-behaviors.md) or inline, not here.

---

### Data-validation findings are computed on every run, then thrown away

**What:** `audit_dataset()` runs the full master validation over the consolidated dataset and
returns `AuditResult(audited, findings, invalid_row_index)`. Its only caller keeps the frame and
drops the rest — `src/whep_digitize/postpro/runner.py:88` reads `.audited` and nothing else. A
grep over `src/` finds no other consumer of `.findings` or `.invalid_row_index`. The audit
workbook that used to carry them (`postpro/audit/export.py`) was deleted, and no replacement
artifact was added, so the findings now have nowhere to go.

**Impact:** Every run pays for the validation and produces no visible result. A dataset with
malformed `value` cells (`"12,5"`, `"n/a"`, stray text) is flagged internally and reported
nowhere — no file, no log line, no diagnostics entry, no non-zero exit. Anyone who relied on
`<dataset>_data_validation_audit.xlsx` now silently gets nothing. Note the audited frame
deliberately *keeps* invalid rows (see pipeline-behaviors.md), so the bad values flow into the
published output unannounced.

**Why it was deferred:** Found during the 2026-09-05 code review of the working tree. Fixing it
means choosing a destination for the findings — a TSV beside the other logs files, an entry in
`PostproDiagnostics.report_paths`, a console summary, or a hard failure above a threshold. That
is a product decision about pipeline output, not a mechanical repair, and the workbook was
removed on purpose.

**Known risks:** Leaving it means the pipeline has a validation stage whose output is
unobservable, which invites the assumption that a clean run means clean data. Whichever
destination is chosen adds a new output artifact, so it needs a parity/contract decision too.

**When to revisit:** Before the next release that anyone consumes the published TSVs from, or
whenever someone asks "why is there no audit workbook any more".

**Fix prompt:**
> `audit_dataset()` in `src/whep_digitize/postpro/audit/audit.py` returns `findings` and
> `invalid_row_index`, and `postpro/runner.py:88` discards both. Decide where validation
> findings should surface and wire them up: the most consistent option is a
> `data_validation_logs.tsv` written next to the per-stage logs TSVs by
> `persist_postpro_logs`, added to the returned `output_paths` and therefore to
> `PostproDiagnostics.report_paths`. Use `_write_logs_tsv` so the rendering matches the other
> logs files. Add a test asserting the file exists and lists the flagged rows for a dataset
> with a known-bad `value`, and update `.claude/docs/pipeline-behaviors.md` to state where
> findings go.

---

### Rules suppressed by D7 first-write-wins leave no diagnostic (12,137 per run)

**What:** When several rules in one `(column_source, column_target)` group match the same
source token on the same row, D7 gives the cell to the first rule in join order and skips the
rest; the losers' target token substitutions are suppressed too. The resolution is deterministic
and documented — the defect is that **nothing records that a rule was suppressed**. No warning,
no audit column, no diagnostic. D9 states this explicitly: token-level collisions are resolved
silently and the per-rule `audit` frame is the only surface, and it reports a suppressed rule no
differently from one that never matched.
Measured on the real dataset (2026-09-09, instrumented full run): **1,034,507** source
competitors across 85 group calls, of which **12,137** lost and were suppressed. The rule files
make this reachable by construction — 6 groups contain a source value used by more than one
rule, one value shared by 42 rules, 665 rules involved.

**Impact:** A rule author cannot tell, from any pipeline output, that 12,137 rule applications
were dropped, nor which rules lost. Two rules differing only in their target condition can both
match a row; whichever sorts first silently wins the source cell. Diagnosing "why didn't my rule
fire?" currently requires instrumenting the engine.

**Why it was deferred:** The engine follows D7 as documented, so there is nothing to repair
without first deciding what should be reported and where. The natural destination is the same
one the entry above needs, which is itself an open product decision — so both should be settled
together rather than inventing two separate diagnostic surfaces.

**Known risks:** Leaving it means the suppression stays invisible and grows quietly as rules are
added; a rule file can accumulate dead rules that look active. Any fix is additive (a new
diagnostic artifact), so it needs an output-contract decision, but it does not move published
data — the resolution itself is unchanged.

**When to revisit:** Together with the validation-findings entry above, or at the next rule-file
review, or whenever someone asks why a rule that appears to match produced no change.

**Fix prompt:**
> In `src/whep_digitize/postpro/rule_engine/conditional_group.py`, `_apply_source_rewrite`
> already computes `losing_joined_idxs` — the rules D7 suppressed — and the caller passes them
> to both target paths. Nothing reports them. Confirm the scale first by counting them across a
> real run (12,137 as of 2026-09-09). Then surface them: join the losing `__joined_idx__` values
> back to `normalize_rules` to recover `(column_source, value_source_raw, column_target,
> value_target_raw)` and emit a suppressed-rule count per rule, alongside the per-stage logs
> TSVs written by `persist_postpro_logs`. Reuse `_write_logs_tsv` so the rendering matches.
> Add a test asserting a suppressed rule appears with a non-zero count, and update D9 in
> `.claude/docs/pipeline-behaviors.md`, which currently states that no such diagnostic exists.

### Multi-token source cells keep only one target value (alphabetically-first token wins)

**What:** When a source cell holds several tokens (e.g. `polity = "israel; palestine"`) and each
token's rule rewrites the **same target token** (here the year tag `iso-1952` in `iso_whep`) to a
different value, only one value survives. `_apply_target_token_rewrite`
(`postpro/rule_engine/conditional_group.py`) resolves the collision with D7 first-write-wins over
the joined frame, which is sorted by `(row_id, __whep_token_index__, __whep_rule_order__)`.
The source-token index comes first, and tokens are sorted, so the **alphabetically-first source
token** wins, not the first rule. D7 is documented for rules competing on one token; this case
(different source tokens, same target token) is not described anywhere.

**Impact:** Measured 2026-10-02 on production, harmonize `polity_iso` sheet: 14,864 rows in 529
(cell, year) groups lost every code but one, e.g. `israel; palestine` → `isr-1948-1967` instead
of `isr-1948-1967; pse-1948-2025`, `french lebanon; french syria` lost `syr-1922-1946`,
`british kenya; british uganda` lost Uganda's. Published `iso_whep` misattributes combined
territories to one member.

**Why it was deferred:** Fixing it changes D7 semantics and therefore published data, possibly
in other column groups too; it needs the owner's decision. Raised with the user 2026-10-02.

**Known risks:** Until fixed, every combined-territory row in `iso_whep` carries one arbitrary
member's code. Any rule group where two source tokens map one target token differently is
affected the same way.

**When to revisit:** As soon as the owner decides how combined cells should be coded.

**Fix prompt:**
> In `src/whep_digitize/postpro/rule_engine/conditional_group.py`, `_apply_target_token_rewrite`
> keeps the first substitution per target token (`if token not in subs`). Change it so that when
> the competing substitutions for one target token come from **different source tokens** of the
> row (distinct `__whep_token_index__`), all their values are kept and the token is replaced by
> their canonical union, while competition from the **same** source token keeps D7
> first-write-wins. Carry `__whep_token_index__` into the `updates` selection to tell the cases
> apart. Measure the blast radius first: count, on production, the target tokens that receive
> different values from different source tokens, per rule group, and report any group other
> than `polity`→`iso_whep`. Add a test with `polity = "israel; palestine"` and two rules
> mapping `iso-1952` to different codes, asserting both codes in either rule order; update D7 in
> `pipeline-behaviors.md`; run the parity suite.

### `#EXACT# #ANY#` in `value_source_raw` acts as a wildcard, not a literal match

**What:** `pipeline-behaviors.md` states that `#EXACT#` suppresses `#ANY#`, so `#EXACT# #ANY#`
matches the literal text `#ANY#`. That holds on the **target** side only. On the **source** side,
`_build_normalize_rules` (`postpro/rule_engine/conditional_group.py`) tests the wildcard on the
resolved body without checking the exact flag, so the rule keys on the wildcard candidate and
matches every row. Reproduced 2026-10-02: data `polity = ["spain", "#ANY#"]`, rule
`polity, #EXACT# #ANY#, , unit, t, X` rewrote both rows' `unit` to `X`; a literal match would
rewrite only the second.

**Impact:** A rule meant to target cells that literally hold `#ANY#` instead fires on every row
of the group's source column. No production rule file uses `#EXACT# #ANY#` on the source side
(scanned 2026-10-02: 4,739 clean/harmonize rules), so no published output is affected today.

**Why it was deferred:** Found while implementing `#REPLACE#` (D12), whose source-side detection
does honour `#EXACT#` via the shared `is_replace_match_directive`. Fixing `#ANY#` changes the
matching semantics of an existing directive, which is a separate concern from adding a new one.

**Known risks:** Low while no rule uses the combination; a future source-side `#EXACT# #ANY#`
rule would silently over-match.

**When to revisit:** Before anyone authors a source-side `#EXACT# #ANY#` rule, or at the next
rule-engine change.

**Fix prompt:**
> In `src/whep_digitize/postpro/rule_engine/conditional_group.py`, `_build_normalize_rules`
> builds `rule_is_source_wildcard` from `(body or "").strip(...).casefold() == wildcard_casefold
> for body, _ in resolved_source`, ignoring the `is_exact` half of each pair. Require
> `not is_exact` (mirror `matching_values._is_wildcard`), so `#EXACT# #ANY#` stays an exact rule
> keyed on its literal body. Add a test in `tests/postpro/test_conditional_group.py` with data
> `polity = ["spain", "#ANY#"]` and source condition `#EXACT# #ANY#` asserting only the second
> row's target changes, then run the parity suite and remove this entry.

### Rule template workbooks are not byte-reproducible

**What:** `clean_harmonize_template.xlsx` and `standardize_units_template.xlsx` (written under
`data/postpro/templates/` every run) embed the wall-clock time in `docProps/core.xml`
(`dcterms:created` / `modified`), so two runs of identical code over identical inputs produce
different bytes. Confirmed 2026-10-02: generating the clean/harmonize template twice gave two
digests whose only differing zip member was `docProps/core.xml`. The lists workbooks already
avoid this by pinning `created` (`export/lists/write.py`, `_WORKBOOK_EPOCH`).

**Impact:** Violates the project's determinism rule ("identical inputs + options → identical
outputs") for these two files only. The cell contents are identical, and the templates are
authoring aids rather than published data, so no dataset is affected; but a byte-level
run-vs-run comparison (as used to verify engine changes) must exclude them.

**Why it was deferred:** Found while verifying `#REPLACE#` (D12) on production data; unrelated
to that change.

**Known risks:** Low. Any tool that diffs or checksums `data/postpro/` between runs sees a
spurious change.

**When to revisit:** Next time the template writers are touched, or if run-to-run byte
comparison of `data/postpro/` becomes part of CI.

**Fix prompt:**
> `src/whep_digitize/postpro/utilities/templates.py` (`Workbook()` … `workbook.save(...)`,
> ~line 195) and the standardize-units template writer in
> `src/whep_digitize/postpro/standardize_units/orchestration.py` save openpyxl workbooks with the
> default wall-clock `created`/`modified` properties. Pin both to the fixed epoch the lists
> export uses (`_WORKBOOK_EPOCH` in `export/lists/write.py`; move it to `setup/constants.py` so
> both share it) via `workbook.properties.created` / `.modified` before saving. openpyxl's zip
> member timestamps may also need pinning; verify by generating each template twice and
> asserting identical bytes in a test, then remove this entry.

---

<!-- Resolved, kept only as precedent for the level of detail expected:
     - Broken `empty_overwrite_events_df` import: an incomplete `overwrite_events` removal left
       `conditional_group.py` importing a deleted symbol and reading a deleted
       `TargetApplyResult` field, so the package would not import and 9 test modules could not
       collect. Fixed by deleting `ConditionalGroupResult.overwrite_events` and its 3 call
       sites — no strategy produced events any more (2026-09-05).
     - NULL source conditions never matched: `_RULE_IS_EXACT` was not set for a NULL
       `value_source_raw`, so such a rule satisfied none of the three `source_matched` branches
       and silently no-opped. Fixed by flagging a NULL source condition as a full-cell match,
       symmetric with the target side (2026-09-05). Changes published data; see
       pipeline-behaviors.md → D10.
     - CI fork deadlock: a default-`fork` ProcessPoolExecutor deadlocked against the polars
       thread pool on Linux; fixed by pinning a `spawn` context (2026-07-23).
     - Rule-table CSV nulls: the CSV branch kept the literal "NA" as a string instead of null;
       fixed with explicit null values (2026-07-23).
     - Unit-conversion float divergence on 3 rows: root cause was the reader's lossy float→text
       coercion, not the conversion arithmetic; fixed by the double-read precision repair in
       `ingest/reading/sheet_read.py` (2026-07-31). See pipeline-behaviors.md → Import.
-->
