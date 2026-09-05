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
means choosing a destination for the findings — a TSV beside the other audit files, an entry in
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
> `data_validation_audit.tsv` written next to the per-stage audit TSVs by
> `persist_postpro_audit`, added to the returned `output_paths` and therefore to
> `PostproDiagnostics.report_paths`. Use `_write_audit_tsv` so the rendering matches the other
> audit files. Add a test asserting the file exists and lists the flagged rows for a dataset
> with a known-bad `value`, and update `.claude/docs/pipeline-behaviors.md` to state where
> findings go.

---

### Ambiguous rule collisions are resolved silently (8,571 rows in the real dataset)

**What:** When two rules in one `(column_source, column_target)` group match the **same source
token** on the **same row**, `_apply_source_rewrite` writes both into
`token_substitutions[row_id][token_value]`, so the last one in join order wins. That is the
documented D7 behaviour and the engine is not misbehaving — the defect is that nothing records
that a choice was made. No warning, no audit column, no diagnostic.
Measured on the real dataset (2026-09-05, instrumented full run): **9,008** substitutions were
written twice for the same `(row, token)`, of which **8,571** wrote a *different* value — a real
conflict silently resolved. Example: row 58499, token `sugar`, `'sugar: cane'` overwritten by
`'sugar: centrifugal'`. The rule files make this reachable by construction: 6 groups contain a
source value used by more than one rule (up to 42 rules sharing one value, 665 rules involved).

**Impact:** 8,571 rows of published data take one of two candidate values with no record of the
alternative. Because the rules differ only in their target condition, both conditions matched
the same row — so this is ambiguous rule authoring the engine cannot detect for the author.
Rule authors have no way to find these rows short of instrumenting the engine.

**Why it was deferred:** Found while resolving CHANGELOG entry E08 on 2026-09-05. The engine
follows D7 as documented, so there is nothing to "fix" without first deciding what the correct
outcome is: (a) emit a diagnostic and keep last-wins, (b) treat a differing collision as a rule
error and fail, or (c) define a precedence other than join order. Only the rule owner can pick.

**Known risks:** Options (b) and (c) change published data for those 8,571 rows. Option (a) is
additive but needs somewhere to put the diagnostic — see the entry above, which has the same
question. Leaving it means the ambiguity stays invisible and may quietly grow as rules are added.

**When to revisit:** Before the next rule-file review, or whenever a commodity value looks
inconsistent between rows that appear to match the same rule.

**Fix prompt:**
> In `src/whep_digitize/postpro/rule_engine/conditional_group.py`, `_apply_source_rewrite` (and
> its target twin `_apply_target_token_rewrite`) resolve same-token collisions by last-write-wins
> into a dict, per D7. Confirm the scale first by counting, per call, `(row_id, token_value)`
> keys written more than once with differing values — the real dataset produced 8,571. Then
> implement the decision: if a diagnostic is wanted, collect the discarded candidates and surface
> them the same way the validation findings are surfaced (see the entry above), and document the
> new column in `.claude/docs/pipeline-behaviors.md` next to D7. Do not change the resolution
> order without a parity run — it moves published data.

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
