# CHANGELOG.md

FORMAT: llm-optimized-v1
AUDIENCE: agent-only. Not human-facing. No prose, no narrative, no decoration.
ROLE: staging queue of un-audited changes (CLAUDE.md > "CHANGELOG.md management protocol").
BASE: 6ab13be | STATE: uncommitted working tree
AUDIT_PASS: 2026-09-05 (pass 4) — queue drained to one entry; every rule-engine entry is fixed and retired.
TREE_STATUS: **GREEN**. 813 tests collect, 813 pass, parity included. `src/whep_digitize` + `tests` clean under ruff and mypy. Every remaining repo-wide gate failure is E15.

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

RETIRED IDs (fixed or verified-integrated; never reuse): E01–E14, E16, E17.

Defects found but deliberately unfixed do NOT live here — they belong in
[deferred-bugs.md](.claude/docs/deferred-bugs.md), which currently holds two, both awaiting a
product decision: validation findings are computed and discarded, and ambiguous same-token rule
collisions are resolved silently (8,571 rows).

---

## E15 | scope | BUG-OPEN | P2-behavior | audit=OPEN (verified; not integrated, sole cause of every repo-wide gate failure)

S:  `scope.main()`, `scope._bootstrap_src_path()`, package `src/scope/` (`config.py`, `dashboard.py`, `data_loader.py`, `main.py`, `quality_flags.py`, `transformers.py`, `visualizations.py`, `__version__ = "0.1.0"`)
F:  UNTRACKED (`git status --porcelain`=`??`): `scope.py` (root, 69L), `src/scope/` (8 files; `visualizations.py` 61.5KB, `dashboard.py` 38.5KB), `tests/scope/` (`test_product_density.py`, `test_quality_flags.py`, `test_transformers.py`)
A:  standalone CLI — root `scope.py` prepends local `src/` to `sys.path`, delegates to `scope.main.run`. Loads tabular pipeline outputs, tags provenance, flags aggregate rows / outliers / controlled-vocabulary violations, renders a Plotly interactive HTML dashboard. Depends on pandas + plotly (NOT polars) — outside the project's polars-only engine standard, and outside the published package (cf. commit `4c0c7f5`).
I:  not wired into `pyproject.toml` entry points; does not affect the digitization pipeline. It is the **sole** cause of every repo-wide gate failure — `src/whep_digitize` and `tests` are clean under both ruff and mypy, and 100% of the remaining 183 ruff errors and 51 mypy errors are scope's.
X:  ruff: 183 errors, 100% inside `scope.py`/`src/scope/`/`tests/scope/`; mypy: 51 errors (mostly `[import-untyped]`, no pandas stubs; plus 4 `no-any-return` in `quality_flags.py:176,179,188,191` and 1 `[assignment]` in `main.py:125`); module-resolution collision: root `scope.py` vs `src/scope/__init__.py` aborts mypy under default resolution.
M:  decide scope's status — vendor it properly, move it out of the repo, or exclude it from the lint/type config — before any repo-wide gate can be green. Nothing else blocks that.
V:  RUN@2026-09-05:`py -3.14 -m ruff check .`=183 errors; RUN:`py -3.14 -m ruff check src/whep_digitize tests`=**All checks passed!**; RUN:`py -3.14 -m mypy`=51 errors in 9 files; RUN:`py -3.14 -m mypy src/whep_digitize`=**no issues in 83 source files**; RUN:`py -3.14 -m mypy src/scope scope.py`=`Duplicate module named "scope"`; RUN:`git status --porcelain`.

---

## GATE_STATE @ 2026-09-05 pass 4 (executed; supersedes every earlier count)

| gate | command | result |
|---|---|---|
| collection | `py -3.14 -m pytest -q --collect-only` | **813 tests collected, 0 errors** |
| pytest | `py -3.14 -m pytest -q` | **813 passed, 0 failed** |
| parity | `py -3.14 -m pytest tests/parity/ -q` | **185 passed** — goldens unchanged throughout |
| ruff pkg | `py -3.14 -m ruff check src/whep_digitize tests` | **PASS** |
| ruff repo | `py -3.14 -m ruff check .` | 183 errors, 100% in scope (E15) |
| mypy pkg | `py -3.14 -m mypy src/whep_digitize` | **PASS** — no issues in 83 source files |
| mypy repo | `py -3.14 -m mypy` | 51 errors in 9 files, 100% in scope (E15) |
| dead symbols | AST usage scan over `src/` + `tests/` | **0** |

Real-data pipeline 478s → ~93s across four optimizations, outputs byte-identical at every step
(14 files compared, including the 94MB and 92MB TSVs). Details in
[.claude/progress.md](.claude/progress.md).

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
