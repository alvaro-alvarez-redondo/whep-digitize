# Prompt for clean session: Replace last-rule-wins with first-rule-wins + multi-pass retry

Copy everything below this line into a fresh Claude session (Opus 5 or Fable 5 recommended).

---

## Task

Replace the `last_rule_wins` collision resolution in the WHEP digitization rule engine with `first_rule_wins` + multi-pass retry semantics. This is a **behavior-changing** fix that affects published data (~8,571 rows in the real dataset). Deliver the complete implementation with passing tests, updated documentation, and no regressions.

## Context

### Project

`whep-digitize` is a deterministic four-stage Python/Polars pipeline: setup (0) → ingest (1) → postpro (2) → export (3). Python 3.14, Polars is the sole dataframe engine. The rule engine lives in the postpro (stage 2) clean/harmonize layers.

Repository root: `c:\Users\Usuario\Nextcloud\whep_alvaro\digitization\whep-digitize`

### Run commands (this host)

```bash
# Gates
py -3.14 -m pytest -q
py -3.14 -m ruff check .
py -3.14 -m mypy

# Full pipeline
py -3.14 -m whep_digitize
```

No `uv` available on this host. Use `py -3.14` for Python.

### What is broken

When two rules in the same `(column_source, column_target)` group match the **same source token** on the **same row** but have **different target conditions**, both rules fire simultaneously in the cartesian join. In `_apply_source_rewrite()` (and `_apply_target_token_rewrite()`), both write to `token_substitutions[row_id][token_value]`, so the **last one in join order wins** (alphabetical by `value_target_raw`).

**Concrete example:**
- Row: `commodity="cotton"`, `footnotes="sea island; stripped"`
- Rule A: `commodity="cotton"`, footnotes contains `"sea island"` → `commodity="cotton (sea island)"`
- Rule B: `commodity="cotton"`, footnotes contains `"stripped"` → `commodity="cotton: raw"`
- Both rules match (same source token "cotton", both target conditions satisfied via token membership)
- Current (wrong): Rule B wins alphabetically ("stripped" > "sea island") → `commodity="cotton: raw"` (generic)
- Expected (correct): Rule A wins (first in order) → `commodity="cotton (sea island)"` (specific). Rule B should NOT apply to this token, but should remain available for the **next multi-pass iteration** in case the first pass changes the target column state.

### Root cause location

**`src/whep_digitize/postpro/rule_engine/conditional_group.py`**

- `_apply_source_rewrite()` line ~562:
  ```python
  token_substitutions.setdefault(row_id, {})[token_value] = value  # LAST WRITE WINS
  ```
- `_apply_target_token_rewrite()` line ~720:
  ```python
  token_substitutions[row_id][token] = values[idx]  # LAST WRITE WINS
  ```

The docstring of `_apply_source_rewrite` says: *"Where several rules hit the same token, the last in join order wins."* This needs to change.

### Why last-rule-wins exists

It was **never** intentionally removed. The commit `e4ae706` ("legacy purged") deleted a separate `footnote_rules.py` engine and explicitly adopted last-rule-wins for the unified `conditional_group.py` engine. The commit message states: *"precedence is last-rule-wins per token, not remove > replace > original"*. The bug was identified and documented in `deferred-bugs.md` at HEAD but deferred pending a product decision.

### The correct design (confirmed by rule owner)

**First-rule-wins + multi-pass retry:**

1. When multiple rules match the same token, the **first rule in sort order** wins for that token.
2. Rules that did NOT apply (their target condition didn't match, or they lost a collision) are **not discarded** — they remain available for the **next multi-pass iteration**.
3. The multi-pass loop already exists in `src/whep_digitize/postpro/clean_harmonize/layer_runner.py` (`run_rule_stage_layer_batch()`, max 10 passes, convergence on zero changes). After Pass 1 rewrites a target column, Pass 2 may find that previously-losing rules now match because the target state changed.

### Implementation approach: Option C (decompose colliding groups)

**DO NOT** change `_apply_source_rewrite()` or `_apply_target_token_rewrite()` directly. Instead, change `build_conditional_rule_dictionary()` in `schema_validation.py` so that groups with collision potential are split into sub-groups where each sub-group has at most one rule per `value_source_raw`. This way:

- Each sub-group processes one rule per source token → no collision possible within a sub-group.
- Sub-groups are applied sequentially by `apply_rule_payload()` in `payload_application.py`.
- The multi-pass loop in `layer_runner.py` naturally handles the "retry" semantics: a rule in sub-group 2 that didn't match in Pass 1 may match in Pass 2 if sub-group 1 changed the target column.
- Non-colliding groups remain unchanged (zero overhead for the majority of groups).

**Real dataset impact:**
- 943 total rules, 7 `(column_source, column_target)` groups
- Only ~6 groups have collision potential (multiple rules sharing `value_source_raw`)
- The largest collision group is `commodity → footnotes` with 101 duplicate source values (730 rules involved)
- Expected performance impact: <1% of current ~93s pipeline time

### Files to modify

| File | Change |
|------|--------|
| `src/whep_digitize/postpro/rule_engine/schema_validation.py` | `build_conditional_rule_dictionary()`: detect groups with duplicate `value_source_raw`, split into sub-groups (one rule each per colliding source value). Maintain sort order. |
| `src/whep_digitize/postpro/rule_engine/conditional_group.py` | Update docstrings: `_apply_source_rewrite()` and `_apply_target_token_rewrite()` — remove "last in join order wins" language. The collision is now prevented upstream. |
| `tests/postpro/test_conditional_group.py` | `test_target_same_token_last_rule_wins()` (line ~265): change assertion from `"AA; b"` to `"A; b"` (first rule wins). Rename test to `test_target_same_token_first_rule_wins()`. |
| `tests/postpro/test_conditional_group.py` | Add new test: two rules matching same token, first wins, second does NOT apply in the same pass. |
| `.claude/docs/pipeline-behaviors.md` | Replace D7 (last_rule_wins) with new D7 describing first-rule-wins + multi-pass retry. Update the "Multiple rules, same token" example in the concrete examples section. |
| `.claude/docs/deferred-bugs.md` | Remove the "Ambiguous rule collisions are resolved silently" entry (mark as fixed). |
| `.claude/docs/pipeline-behaviors.md` | Add a new section explaining the group decomposition strategy and WHY first-rule-wins was chosen over last-rule-wins. |

### Detailed implementation for `build_conditional_rule_dictionary()`

Current function signature (line ~346 of `schema_validation.py`):

```python
def build_conditional_rule_dictionary(
    rules_df: pl.DataFrame, stage_name: str
) -> list[pl.DataFrame]:
```

Current behavior: groups by `(column_source, column_target)`, sorts rules within each group by `(value_source_raw, value_target_raw, value_target)`, returns one DataFrame per group.

**New behavior:** After extracting each group, check if any `value_source_raw` appears more than once. If so, split the colliding source values into individual sub-groups (one rule per sub-group), keeping non-colliding rules together. Maintain the existing sort order.

Pseudocode:
```python
for column_source, column_target in present_groups.iter_rows():
    group_df = ordered_rules.filter(...)
    
    # Find value_source_raw values that appear more than once
    collision_sources = (
        group_df.group_by("value_source_raw")
        .agg(pl.len().alias("count"))
        .filter(pl.col("count") > 1)
        .get_column("value_source_raw")
        .to_set()
    )
    
    if collision_sources:
        # Each colliding source value gets its own sub-group
        for src_val in sorted(collision_sources):
            sub = group_df.filter(pl.col("value_source_raw") == src_val)
            groups.append(sub)
        # Non-colliding rules stay together
        non_colliding = group_df.filter(
            ~pl.col("value_source_raw").is_in(collision_sources)
        )
        if non_colliding.height > 0:
            groups.append(non_colliding)
    else:
        # No collisions — keep as-is
        groups.append(group_df)
```

**Important:** The sort order of sub-groups matters for determinism. Colliding source values should be emitted in their sorted order (ascending by `value_source_raw`), followed by the non-colliding block. This maintains the existing alphabetical determinism.

### Test changes

1. **`test_target_same_token_last_rule_wins()`** → rename to `test_target_same_token_first_rule_wins()`:
   - Two rules: `("commodity", "rice", None, "unit", "a", "A")` and `("commodity", "rice", None, "unit", "a", "AA")`
   - Current assertion: `result.data.get_column("unit").to_list() == ["AA; b"]`
   - New assertion: `result.data.get_column("unit").to_list() == ["A; b"]`
   - Update docstring to describe first-rule-wins

2. **New test — `test_collision_group_decomposition()`**:
   - Create a rule group where two rules share `value_source_raw` but have different `value_target_raw`
   - Verify that `build_conditional_rule_dictionary()` splits them into separate sub-groups
   - Verify that applying the groups results in first-rule-wins behavior

3. **New test — `test_multi_pass_retry_after_collision()`**:
   - Row with `commodity="cotton"`, `footnotes="sea island; stripped"`
   - Rule A: cotton + "sea island" → "cotton (sea island)"
   - Rule B: cotton + "stripped" → "cotton: raw"
   - Pass 1: Rule A wins (first in order), commodity becomes "cotton (sea island)", footnote "sea island" is removed
   - Pass 2: Rule B's target condition ("stripped") still matches the remaining footnote → Rule B now applies
   - Verify both rules eventually apply across passes

### Documentation changes

**`.claude/docs/pipeline-behaviors.md`:**

Replace D7:
```
- **D7 — `last_rule_wins` at token level.** When multiple rules match the **same
  token**, the last rule in rule order wins for that specific token.
```

With:
```
- **D7 — First rule wins at token level + multi-pass retry.** When multiple rules
  in one group match the **same source token** on the same row, the **first rule in
  sort order** wins for that token. The other rules are not discarded — they remain
  available for subsequent multi-pass iterations. If the winning rule changes the
  target column state (e.g., removes a footnote token), a previously-losing rule may
  match in the next pass. Groups with collision potential (multiple rules sharing
  `value_source_raw`) are automatically decomposed into sub-groups by
  `build_conditional_rule_dictionary()` so each sub-group applies at most one rule
  per token, eliminating intra-group collisions.
  Example: target `"a; b; c"` with two rules `"a"` → `"A"` and `"a"` → `"AA"` yields
  `"A; b; c"` (Rule 1 wins).
```

Update the concrete examples table:
```
**Multiple rules, same token (first wins):**
Cell: "a; b; c"
Rule 1: "a" → "A"
Rule 2: "a" → "AA"
Result: "A; b; c"  (Rule 1 wins for token "a")
```

**`.claude/docs/deferred-bugs.md`:**

Remove the entire "Ambiguous rule collisions are resolved silently (8,571 rows in the real dataset)" entry. The bug is fixed.

**New design document:** Create `.claude/docs/design/first-rule-wins.md` explaining:
1. WHY first-rule-wins over last-rule-wins (specificity: more specific target conditions tend to sort first alphabetically, and the "retry" semantics mean less-specific rules get a chance in subsequent passes)
2. WHY group decomposition over in-engine collision handling (atomicity, no shared mutable state, deterministic ordering, minimal code change surface)
3. Performance analysis: ~6 groups affected out of ~665 total rules, <1% overhead
4. The multi-pass retry mechanism and how it interacts with the convergence loop

### Constraints

- **Determinism is non-negotiable.** Identical inputs + options → identical outputs. Sort order must be stable.
- **No global state.** Stages return typed contracts.
- **Polars only.** No pandas.
- **Snake case, full type hints, Google-style docstrings** (enforced by ruff D).
- **Don't stop at partial work.** A change is done only when tests pass + gates pass.
- **Golden files under `tests/golden/` are IMMUTABLE.** If a parity test fails, the behavior change is deliberate — update the golden file ONLY after verifying the new output is correct. The golden comparison is byte-for-byte.
- **One concern per change.** Focused diffs.
- **Log every assumption.** If something is ambiguous, document it rather than guessing.

### Verification checklist

Before marking the task complete, verify:

- [ ] `py -3.14 -m pytest -q` passes (all tests, including parity)
- [ ] `py -3.14 -m ruff check .` passes
- [ ] `py -3.14 -m mypy` passes
- [ ] `test_target_same_token_first_rule_wins()` passes with `"A; b"` assertion
- [ ] New collision decomposition test passes
- [ ] New multi-pass retry test passes
- [ ] D7 in `pipeline-behaviors.md` describes first-rule-wins + multi-pass retry
- [ ] Deferred-bugs.md collision entry is removed
- [ ] Design document exists at `.claude/docs/design/first-rule-wins.md`
- [ ] Docstrings in `conditional_group.py` no longer mention "last in join order wins"
- [ ] No new dead symbols (verify with AST scan or ruff F401)

### Order of operations

1. Read `schema_validation.py` (`build_conditional_rule_dictionary`) and `conditional_group.py` (`_apply_source_rewrite`, `_apply_target_token_rewrite`) to understand current code.
2. Implement group decomposition in `build_conditional_rule_dictionary()`.
3. Update docstrings in `conditional_group.py`.
4. Update `test_target_same_token_last_rule_wins()` → first-rule-wins.
5. Add new tests (collision decomposition, multi-pass retry).
6. Run `py -3.14 -m pytest -q` — expect some parity test failures.
7. For each failed parity test, verify the new output is correct, then update the golden file.
8. Update `pipeline-behaviors.md` (D7, examples table).
9. Remove collision entry from `deferred-bugs.md`.
10. Create `.claude/docs/design/first-rule-wins.md`.
11. Run full gates (pytest, ruff, mypy).
12. Verify no dead symbols.

---

End of prompt.
