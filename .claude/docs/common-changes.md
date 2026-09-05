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

## Add a cleaning rule with target tokenization

Source and target are symmetric: both use token-by-token substitution by value.

1. **Identify the rule type** you need:

   | Goal | Rule type | How to write it |
   |------|-----------|-----------------|
   | Replace one token | Normal | `value_target_raw = "x"` → `value_target = "X"` |
   | Replace entire cell | `#EXACT#` | `value_target_raw = "#EXACT# x; y"` → `value_target = "Z"` |
   | Add a token regardless of current value | `#ANY#` | `value_target_raw = "#ANY#"` → `value_target = "new"` |
   | Fill empty cells only | `None` | leave `value_target_raw` empty → `value_target = "default"` |

   **Note:** `#EXACT#` is independent on source and target sides. Placing `#EXACT#` in
   `value_source_raw` only affects the source column (full-cell match + full-cell override).
   It does NOT cause a full-cell override on the target column. To override the entire target
   cell, place `#EXACT#` in `value_target_raw` as well.

2. **Add the rule row** to the appropriate rules file (clean or harmonize).
   Rule cells are canonicalized on load: split on `;`, trimmed, deduplicated, sorted.
   So `"c; a; b"` becomes `"a; b; c"` automatically.

3. **Remember the semantics:**

   - Normal rules replace only the matching token; siblings are preserved.
   - Multiple rules matching the same token: last rule in rule order wins (D7).
   - `#ANY#` adds a token without replacing; the cell is rebuilt sorted and deduplicated.
   - `#EXACT#` bypasses tokenization entirely.
   - Multi-token values (`"a; b; c"`) in `value_target` are expanded into individual
     tokens during reconstruction.

4. **Tests:** add a test case in `tests/postpro/` covering the specific rule behavior.
   Check [pipeline-behaviors.md](pipeline-behaviors.md) → *Target tokenization* for
   concrete examples.

5. **Run the gates** (ruff, mypy, pytest). If output changes, update the affected golden
   in `tests/golden/` deliberately.

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
