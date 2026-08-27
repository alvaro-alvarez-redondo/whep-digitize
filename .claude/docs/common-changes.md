# Common changes

Recipes for frequent edits. Each lists where, what, tests, watch-outs. **Check here first.**

---

## Change pipeline behavior

1. Check [pipeline-behaviors.md](pipeline-behaviors.md) first — if the behavior is listed there
   it is **intentional**, and changing it changes published data. Confirm that is the intent.
2. Find the module in [codebase-map.md](codebase-map.md); honor the stage's contract
   (`contracts.py`).
3. Implement, then write tests (happy / edge / error).
4. If output changes on purpose, the affected frozen golden under `tests/golden/` must be edited
   deliberately in the same change, and `pipeline-behaviors.md` updated.
5. Run the gates (ruff, mypy, pytest).

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
- **Export lists** — `OutputConfig.lists_to_export` if needed.
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
- `data/` is gitignored; the goldens under `tests/golden/` **are committed** and immutable —
  that is what lets CI enforce output parity. Edit one only as a deliberate behavior change.
- No backward-compatibility scaffolding — remove legacy patterns on sight.
