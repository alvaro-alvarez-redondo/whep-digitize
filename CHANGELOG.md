# CHANGELOG.md

FORMAT: llm-optimized-v1
AUDIENCE: agent-only. Not human-facing. No prose, no narrative, no decoration.
ROLE: staging queue of un-audited changes (CLAUDE.md > "CHANGELOG.md management protocol").
BASE: 0a17997
AUDIT_PASS: 2026-10-14 — queue empty. E15 (scope) closed by deleting the scope package and its tests.
TREE_STATUS: 877 tests collect and pass, parity included; repo-wide ruff check and mypy pass.

## Field grammar

```
## <ID> | <domain> | <class> | <sev> | audit=<state>
S:  symbols (exact identifiers; suffix <removed|new|renamed|read|import>)
F:  files (repo-relative, :line when precise)
B:  before-state
A:  after-state
I:  impact (runtime/consumer consequence)
M:  migration (BREAKING only; exact caller-side action)
R:  rationale (only when it constrains a future decision; else omitted)
X:  contradiction / caveat / known-incomplete
V:  provenance — RUN:<cmd>=<result> | DIFF (static read only) | CLAIM (session self-report, unverified)
```

class ∈ {BREAKING, FEAT, FIX, REFACTOR, PERF, DEPS, DOCS, BUG-OPEN}
sev ∈ {P0-blocking, P1-breaking, P2-behavior, P3-cosmetic}
audit ∈ {DONE (verified; removable once integrated), PENDING (needs verification), OPEN (defect, not removable until fixed)}

Trust rule: `V:CLAIM` lines are unverified assertions. `V:DIFF` = symbol-level confirmed,
runtime behavior NOT confirmed. Only `V:RUN:` lines are executed evidence.

RETIRED IDs (fixed or verified-integrated; never reuse): E01–E17.

Defects found but deliberately unfixed do NOT live here — they belong in
[deferred-bugs.md](.claude/docs/deferred-bugs.md).

---

## GATE_STATE @ 2026-10-14 (executed; supersedes every earlier count)

| gate | command | result |
|---|---|---|
| collection | `py -3.14 -m pytest -q --collect-only` | **877 tests collected, 0 errors** |
| pytest | `py -3.14 -m pytest -q` | **877 passed, 0 failed** |
| parity | `py -3.14 -m pytest tests/parity/ -q` | **187 passed** — goldens unchanged |
| ruff | `py -3.14 -m ruff check .` | **PASS** |
| mypy | `py -3.14 -m mypy` | **PASS** |

## WRITE_RULES (for future entries in this file)

1. Use the field grammar above. No prose paragraphs, no session narrative, no status emoji.
2. Every entry carries `V:`. A claim without executed evidence is `V:CLAIM` or `V:DIFF` — never
   assert completion from either.
3. Every `BREAKING` carries `M:` with the exact caller-side action.
4. Entry IDs are stable and referenced cross-entry. Do not renumber on deletion; see RETIRED IDs.
5. `audit=DONE` + integrated → DELETE the entry. This file is a pending-work queue, not history;
   `git log` is history. `audit=OPEN` entries are never deleted until fixed.
6. A verified-integrated change that leaves residue (dead code, stale docstrings, stale docs) is
   NOT removable. Trim the entry to the residue and keep it `audit=OPEN`.
7. A defect found but deliberately unfixed goes in `.claude/docs/deferred-bugs.md`, not here —
   CLAUDE.md mandates that file. This file tracks un-audited *changes*; that one tracks *bugs*.
