# Common changes

Recipes for frequent edits. Each lists where, what, tests, watch-outs. **Check here first.**

---

## Migrate an R module to Python

The core recurring task. Use the `migrate-module` skill (`.claude/skills/migrate-module/`),
or by hand:

1. Read the R source + its entry in [codebase-map.md](codebase-map.md) (R source + risk).
2. Read [r-to-python-mapping.md](r-to-python-mapping.md) for the idioms and parity risks.
3. Implement in the target module, honoring the stage's contract (`contracts.py`).
4. Write tests (happy / edge / error) + a `@pytest.mark.parity` test vs R golden output.
5. Run the gates (ruff, mypy, pytest). Update the codebase-map entry to **[done]**.

See [guidelines/migration.md](../guidelines/migration.md) for the full playbook.

## Add or change a constant / threshold

- **Where:** `src/whep_digitize/setup/constants.py` (the relevant frozen dataclass).
- **What:** add/edit a field; access via `get_pipeline_constants().<group>.<field>`.
- **Tests:** `tests/setup/test_constants.py` (pins exact values).
- **Docs:** mirror in [constants-and-options.md](constants-and-options.md).

## Add a column to the canonical schema

- **Canonical order** — `Sorting.stage_row_order`.
- **Column role** — add to `Columns` (`base`/`id_vars`/`value`/`system`); import header
  recognition uses `base ∪ id_vars`.
- **Source aliases** — `HeaderNormalization.canonical_aliases`.
- **Export lists** — `ExportConfig.lists_to_export` if needed.
- **Tests:** update `test_constants.py` order assertion; add transform/validate coverage.
- **Watch out:** everything is string-typed until the postpro audit step.

## Add a runtime option

- **Where:** `RuntimeOptions` in `setup/options.py` (env var `WHEP_<UPPER>`).
- **Tests:** add to a config/options test.
- **Docs:** [constants-and-options.md](constants-and-options.md).

## Add a helper function

- Drop it in the right `setup/helpers/<name>.py` (or add a module). Fully typed +
  Google-style docstring. Add tests in `tests/setup/test_helpers.py`.

## Change a cross-stage contract

- **Where:** `contracts.py`. Update the producing stage runner and all consumers.
- **Tests:** `tests/contracts/test_contracts.py`.
- **Docs:** the contracts table in [architecture.md](architecture.md).

## Add or fix a test

- **Where:** the matching `tests/<stage>/` dir. Use `conftest.py` fixtures + temp dirs;
  seed randomness; no network/FS side effects. Parity tests get `@pytest.mark.parity`.

---

## Boundaries

- Single engine: **polars** (immutable). No pandas except at a documented IO boundary.
- No global state; stages return typed results.
- `data/` is gitignored; golden fixtures under `tests/golden/` **are committed** (the frozen R
  reference — that is what makes CI enforce parity; regenerate only via `capture.py`).
- No backward-compatibility scaffolding — remove legacy patterns on sight.
