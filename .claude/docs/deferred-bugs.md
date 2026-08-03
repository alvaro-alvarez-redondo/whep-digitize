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

*The list is currently empty.*

<!-- Resolved, kept only as precedent for the level of detail expected:
     - CI fork deadlock: a default-`fork` ProcessPoolExecutor deadlocked against the polars
       thread pool on Linux; fixed by pinning a `spawn` context (2026-07-23).
     - Rule-table CSV nulls: the CSV branch kept the literal "NA" as a string instead of null;
       fixed with explicit null values (2026-07-23).
     - Unit-conversion float divergence on 3 rows: root cause was the reader's lossy float→text
       coercion, not the conversion arithmetic; fixed by the double-read precision repair in
       `ingest/reading/sheet_read.py` (2026-07-31). See pipeline-behaviors.md → Import.
-->
