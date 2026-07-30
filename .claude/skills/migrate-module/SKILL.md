---
name: migrate-module
description: >-
  Port one R module from whep-digitalization to a Python/polars module in whep-digitize,
  with verified output parity. Use when migrating a specific stage sub-module (e.g.
  "migrate the header normalization", "port 13-validate.R", "implement the ingest reshape").
---

# migrate-module

Migrate a single R module to Python/polars with a passing parity test. This is the core
recurring task of the project. Follow it end-to-end; do not stop at a partial port.

## Inputs

- The target module (by R source file, e.g. `r/1-import_pipeline/13-output/13-validate.R`,
  or by Python destination, e.g. `ingest/output/validate.py`). If ambiguous, pick the next
  unblocked module from [migration-roadmap.md](../../docs/migration-roadmap.md).

## Steps

1. **Locate & scope.**
   - Read the R source in the sibling repo
     `C:/Users/Usuario/Nextcloud/whep_alvaro/digitalization/whep-digitalization/`.
   - Read its [codebase-map.md](../../docs/codebase-map.md) row (R source + risk) and confirm
     its dependencies are already **[done]** (migrate bottom-up).
   - Read the target stage's contract in `src/whep_digitize/contracts.py`.

2. **Study parity risks.** Read [r-to-python-mapping.md](../../docs/r-to-python-mapping.md).
   Note which ranked risks this module touches (transliteration, melt→unpivot, ordering,
   last-rule-wins, NA↔NA, serialize→hash, radix, parse-double quirk, unit-prefix fold,
   in-place mutation) and plan the polars idiom for each.

3. **Capture golden output** (use the `parity-check` skill): run the R function on
   representative fixtures and save outputs under `tests/golden/<module>/`.

4. **Implement** the Python module in its scaffolded location:
   - Honor the stage contract; return typed results, never mutate in place.
   - polars expressions over loops; `helpers.strings`/`sorting`/`numeric` for shared ops.
   - Full type hints + Google-style docstrings; reference the R source in the module docstring.

5. **Test** in the matching `tests/<stage>/` file:
   - happy path, edge cases (empty / all-null / accented / duplicates / wildcard / NA),
     error cases, and a `@pytest.mark.parity` test vs the golden output
     (`polars.testing.assert_frame_equal`, `check_dtypes` deliberate).

6. **Gates:** `.venv/Scripts/python.exe -m ruff check .` and `... -m ruff format .` and
   `... -m mypy` and `... -m pytest -q` — all green. Never lower pass rate.

7. **Record:** flip the module's codebase-map row to **[done]**; append a line to
   `.claude/progress.md`; delete any scratch files; commit.

## Guardrails

- Reproduce documented R quirks exactly (see mapping doc); do not silently "fix" them.
- Normalization follows the documented POLICY (NFD diacritic strip), not R's ICU `Latin-ASCII`.
  Do NOT add character-specific overrides to match ICU's symbol/ligature expansions — pin the
  behavior with a policy test (see `tests/setup/test_helpers.py`).
- Keep the change scoped to one module. If a dependency is missing, migrate it first (or
  note the blocker) rather than stubbing incorrectly.
