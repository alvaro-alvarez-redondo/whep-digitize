---
name: refactoring
description: Audit and modernize Python modules through iterative refactor passes.
---

# Refactoring

Enforce `snake_case`, full type hints, Google-style docstrings, `pathlib` over `os.path`,
`polars` expressions over Python loops. Remove global state, add `pydantic`/guard validation,
route errors through `whep_digitize.setup.errors`. Reduce duplication; separate validation
from transformation. Remove dead code and any backward-compat scaffolding.

## Approach

1. **Analyze** — inefficiencies, redundant patterns, unclear boundaries.
2. **Refactor incrementally** — verify (ruff + mypy + pytest) after each step.
3. **Reassess** — clarity, coverage, typing, modularity. Repeat until no gains remain.
4. **Document** rationale for non-obvious changes.

## Splitting modules

Split at ~300 lines or multiple responsibilities. Keep modules grouped by stage sub-package;
prefer many small, single-purpose modules over god-modules. Splits should be behavior-identical
(verified by tests).

## Constraints

No feature expansion. No contract breaks unless modernization requires (update tests + docs).
Deterministic only. Delete scratch files immediately — leave no temporary artifacts (see the
temp-file policy in [conventions.md](../docs/conventions.md)).
