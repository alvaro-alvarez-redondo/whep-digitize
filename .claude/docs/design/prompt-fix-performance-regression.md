# Prompt: Fix first-rule-wins performance regression (patch existing implementation)

## Primary instruction

Revert the group decomposition approach (`_decompose_group`) and implement first-write-wins
directly in the token substitution dicts. This is a **targeted patch** to the existing
implementation, not a ground-up rewrite.

## Problem context

The whep-digitize pipeline suffers a catastrophic performance regression: ~93s → 20+ minutes.
First-rule-wins was implemented via group decomposition (`_decompose_group` in
`schema_validation.py`), which expands 15 groups → 810 sub-groups (54x). Each sub-group
executes the full `apply_conditional_rule_group()` pipeline (explode, normalize, join, sort,
target match), repeating O(N) work 54x times. Python overhead (~14.5ms/sub-group) dominates
total time.

**Benchmark**: clean_commodity.xlsx (768 rules, 1 group → 718 sub-groups): 46ms → 10,446ms
(225x) with 3,000 rows. Extrapolated to the real dataset (794K rows): ~46 min for that file alone.

**Full analysis**: `.claude/docs/design/performance-regression-first-rule-wins.md`
(Read it if you need more context, but the instructions below are self-contained.)

## Step 1: Remove `_decompose_group` from `schema_validation.py`

File: `src/whep_digitize/postpro/rule_engine/schema_validation.py`

### 1a. Delete the `_decompose_group` function

Remove the entire `_decompose_group()` function (~50 lines, around lines 405-455). Include the
docstring and the full body.

### 1b. Revert the call in `build_conditional_rule_dictionary`

In the loop `for column_source, column_target in present_groups.iter_rows():`, change:

```python
        groups.extend(
            _decompose_group(group_df)
        )
```

to:

```python
        groups.append(group_df)
```

### 1c. Verify no references remain

Grep for `decompose` in the workspace. There should be no remaining references in Python code
(docstrings are updated in Step 4).

## Step 2: First-write-wins in `_apply_source_rewrite`

File: `src/whep_digitize/postpro/rule_engine/conditional_group.py`

In function `_apply_source_rewrite()`, inside the loop `for row_id, token_index, value,
is_source_wildcard in updates.iter_rows():`, change the line:

```python
            token_substitutions.setdefault(row_id, {})[token_value] = value
```

to:

```python
            subs = token_substitutions.setdefault(row_id, {})
            if token_value not in subs:
                subs[token_value] = value
```

**Why this works**: The join is sorted by `__whep_rule_order__`, so loop iterations come in
rule order. If a token already has a substitution, skipping the new one means the first rule
in order wins. O(1) extra per substitution, zero group expansion.

## Step 3: First-write-wins in `_apply_target_token_rewrite`

File: `src/whep_digitize/postpro/rule_engine/conditional_group.py`

In function `_apply_target_token_rewrite()`, inside the loop `for idx in range(len(row_ids)):`
, change:

```python
                    token_substitutions.setdefault(row_id, {})
                    for token in matched:
                        assert token is not None  # filtered above
                        token_substitutions[row_id][token] = values[idx]
```

to:

```python
                    subs = token_substitutions.setdefault(row_id, {})
                    for token in matched:
                        assert token is not None  # filtered above
                        if token not in subs:
                            subs[token] = values[idx]
```

## Step 4: Update docstrings

File: `src/whep_digitize/postpro/rule_engine/conditional_group.py`

### 4a. `_apply_source_rewrite` docstring

Change:
```
    A token match replaces just that token and leaves its siblings intact; an ``#EXACT#`` match
    replaces the whole cell. Collisions (multiple rules hitting the same token) are prevented
    upstream by group decomposition in ``build_conditional_rule_dictionary``, so at most one
    rule applies per token within a sub-group. Each rebuilt cell is canonicalized, so the
    result is deduplicated and sorted.
```

to:
```
    A token match replaces just that token and leaves its siblings intact; an ``#EXACT#`` match
    replaces the whole cell. When multiple rules match the same token, the first rule in join
    order wins (D7) — subsequent substitutions for the same token are skipped. Each rebuilt
    cell is canonicalized, so the result is deduplicated and sorted.
```

### 4b. `_apply_target_token_rewrite` docstring

Change:
```
    A normal token match replaces just that token and leaves siblings intact; an ``#EXACT#``
    replaces the whole cell; ``#ANY#`` adds the new value as an additional token.
    Collisions are prevented upstream by group decomposition, so at most one rule applies
    per token within a sub-group (D7).
```

to:
```
    A normal token match replaces just that token and leaves siblings intact; an ``#EXACT#``
    replaces the whole cell; ``#ANY#`` adds the new value as an additional token.
    When multiple rules match the same token, the first rule in join order wins (D7) —
    subsequent substitutions for the same token are skipped.
```

### 4c. `apply_conditional_rule_group` inline comment

Find the comment:
```
    # Left join keeps every candidate and fans out on a multi-rule match. The
    # (row_id, token-index, rule-order) sort makes that order deterministic. Collisions
    # are prevented upstream by group decomposition, so at most one rule hits a given
    # token within a sub-group.
```

Change to:
```
    # Left join keeps every candidate and fans out on a multi-rule match. The
    # (row_id, token-index, rule-order) sort makes that order deterministic. When
    # multiple rules hit the same token, the first in join order wins (D7).
```

## Step 5: Update tests

### 5a. `test_target_same_token_first_rule_wins` (update docstring)

File: `tests/postpro/test_conditional_group.py`, line ~265

Change the test docstring:
```python
    """D7: when two rules match the same token, first rule wins at token level.

    Colliding groups are decomposed by ``build_conditional_rule_dictionary`` so each
    sub-group applies at most one rule per source token. The first sub-group's rule wins,
    and the second rule remains available for the next multi-pass iteration.
    """
```

to:
```python
    """D7: when two rules match the same token, first rule wins at token level.

    The token substitution dict uses first-write-wins: when two rules in the same group
    match the same token, the first rule in join order (determined by __whep_rule_order__)
    gets its substitution applied, and the second is skipped.
    """
```

Also update the inline comment:
```python
    # Rule 1 wins for token "tok_a" -> "REPLACED_A"; "b" preserved.
    # The colliding group is split into two sub-groups (one rule each).
    # Sub-group 1 applies "tok_a" -> "REPLACED_A", sub-group 2's target condition
    # "tok_a" no longer matches because the token has been replaced.
```

to:
```python
    # Rule 1 wins for token "tok_a" -> "REPLACED_A"; "b" preserved.
    # Both rules are in the same group. Rule 1's substitution is applied first
    # (first-write-wins in token_substitutions dict), so Rule 2's substitution
    # for the same token is skipped.
```

### 5b. `test_collision_group_decomposition_e2e` (rename + update docstring)

File: `tests/postpro/test_conditional_group.py`, line ~634

Change the name and docstring:
```python
def test_collision_group_decomposition_e2e() -> None:
    """Two rules matching same token via payload_application: first rule wins.

    Verifies that build_conditional_rule_dictionary decomposes colliding groups
    and that apply_rule_payload applies sub-groups sequentially, so the first
    rule's substitution prevents the second rule's target condition from matching.
    """
```

to:
```python
def test_collision_first_rule_wins_e2e() -> None:
    """Two rules matching same token via payload_application: first rule wins.

    Verifies that when two rules in the same group share value_source_raw but differ
    in value_target_raw, the first rule in join order wins via first-write-wins in the
    token substitution dict. The group is NOT decomposed.
    """
```

The test body and assertions do not need to change (the observable behavior is the same:
first rule wins).

### 5c. `test_multi_pass_retry_after_collision` (update docstring)

File: `tests/postpro/test_conditional_group.py`, line ~668

Update the docstring to remove "decomposition" references:
```python
    """Multi-pass loop allows a losing rule to apply in a subsequent pass.

    Pass 1: Rule A wins (first in order), rewrites target column.
    Pass 2: Rule B's target condition still matches the remaining tokens,
    so Rule B now applies (it lost in Pass 1 because Rule A's substitution
    changed the target state, but the multi-pass loop retries).

    This test exercises the full layer_runner multi-pass loop.
    """
```

to:
```python
    """Multi-pass loop with first-write-wins: losing rule may apply in a subsequent pass.

    Pass 1: Rule A wins (first in join order via first-write-wins), rewrites commodity.
    Rule B's source condition "cotton" no longer matches "cotton_sea".
    Pass 2: Rule B's source condition still doesn't match. Converged.

    This verifies that first-write-wins resolves the collision within a single group
    without group decomposition.
    """
```

Also update inline comments that mention "decomposition":
```python
    # After decomposition, Rule A and Rule B are in separate sub-groups.
    # Pass 1: Rule A applies (first sub-group), commodity → "cotton_sea".
    #   Rule B's source condition is "cotton", but commodity is now "cotton_sea" → no match.
```

to:
```python
    # Rule A and Rule B share value_source_raw="cotton" but differ in value_target_raw.
    # They are in the same group. Rule A wins via first-write-wins.
    # Pass 1: Rule A applies, commodity → "cotton_sea".
    #   Rule B's source condition is "cotton", but commodity is now "cotton_sea" → no match.
```

And the final comment:
```python
    # Rule A (first in sort order) wins: commodity → "cotton_sea", footnote cleared.
    # Rule B's source condition "cotton" no longer matches "cotton_sea".
    # changed_value_count == 2: commodity changed + footnotes changed (tok_sea removed).
```

(Remove the line "We test through apply_rule_payload (single pass) to verify decomposition.")

### 5d. `test_dictionary_decomposes_colliding_source_values` (rewrite)

File: `tests/postpro/test_schema_validation.py`, line ~334

Replace the entire test:
```python
def test_dictionary_decomposes_colliding_source_values() -> None:
    """Groups with duplicate value_source_raw are split into single-rule sub-groups."""
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity", "commodity"],
            "value_source_raw": ["rice", "rice", "wheat"],
            "column_target": ["unit", "unit", "unit"],
            "value_target_raw": ["a", "b", "c"],
            "value_target": ["v1", "v2", "v3"],
        }
    )
    groups = build_conditional_rule_dictionary(rules, "clean")
    # "rice" appears twice → each rule gets its own sub-group.
    # "wheat" appears once → stays in the non-colliding block.
    assert len(groups) == 3
    # First colliding rule (sorted by value_target_raw: "a" < "b").
    assert groups[0].height == 1
    assert groups[0].get_column("value_source_raw").to_list() == ["rice"]
    assert groups[0].get_column("value_target_raw").to_list() == ["a"]
    # Second colliding rule.
    assert groups[1].height == 1
    assert groups[1].get_column("value_source_raw").to_list() == ["rice"]
    assert groups[1].get_column("value_target_raw").to_list() == ["b"]
    # Non-colliding block.
    assert groups[2].height == 1
    assert groups[2].get_column("value_source_raw").to_list() == ["wheat"]
```

with:
```python
def test_dictionary_no_decomposition_of_colliding_source_values() -> None:
    """Groups with duplicate value_source_raw are kept together (no decomposition).

    First-write-wins is handled in the token substitution dict, not by splitting groups.
    """
    rules = _canonical_rules(
        {
            "column_source": ["commodity", "commodity", "commodity"],
            "value_source_raw": ["rice", "rice", "wheat"],
            "column_target": ["unit", "unit", "unit"],
            "value_target_raw": ["a", "b", "c"],
            "value_target": ["v1", "v2", "v3"],
        }
    )
    groups = build_conditional_rule_dictionary(rules, "clean")
    # All 3 rules stay in a single group (no decomposition).
    assert len(groups) == 1
    assert groups[0].height == 3
```

### 5e. `test_dictionary_no_decomposition_without_collisions` (rename + simplify)

File: `tests/postpro/test_schema_validation.py`, line ~362

Change:
```python
def test_dictionary_no_decomposition_without_collisions() -> None:
    """Groups with unique value_source_raw are not decomposed."""
```

to:
```python
def test_dictionary_groups_by_source_target_columns() -> None:
    """Rules are grouped by (column_source, column_target) without decomposition."""
```

The test body does not need to change.

### 5f. `test_run_detects_cycle_and_warns` (verify)

File: `tests/postpro/test_clean_harmonize.py`, line ~259

This test verifies that a 2-rule oscillation converges. With first-write-wins (instead of
decomposition), the behavior differs but the final result is the same: both rules are in the
same group, Rule 1 applies (a→b), Rule 2 tries to apply (b→a) but its target condition
doesn't match because the target column value is "a", not "b".

**IMPORTANT**: Verify this test still passes. With first-write-wins:
- Both rules are in the same group (no decomposition)
- Rule 1: commodity=x, unit=a → unit=b
- Rule 2: commodity=x, unit=b → unit=a
- Both rules share `value_source_raw` ("x"), so they compete for the same source token
- But they act on different target conditions (one writes "b", the other writes "a") in the
  same `unit` column
- Rule 1's target condition is "a", Rule 2's target condition is "b"
- The dataset has unit="a", so only Rule 1's target condition matches
- Rule 2 doesn't match because unit="a" ≠ "b"

The test should still pass without changes, but **verify it**. If it fails, adjust the
assertions to match the new behavior. Also update the docstring to remove decomposition
references.

## Step 6: Update documentation

### 6a. `pipeline-behaviors.md` — D7

File: `.claude/docs/pipeline-behaviors.md`

Change the D7 section:
```
- **D7 — `first_rule_wins` via group decomposition.** When multiple rules in the same
  `(column_source, column_target)` group share the same `value_source_raw` but differ in
  `value_target_raw`, the group is decomposed into single-rule sub-groups during schema
  validation. Each sub-group is applied sequentially in rule order. The first matching
  rule wins because its substitution may invalidate the target condition of later
  sub-groups. Example: target `"a; b; c"` with two rules `"a"` → `"A"` and `"a"` → `"AA"`
  yields `"A; b; c"` (the first sub-group rewrites `"a"` to `"A"`, so the second sub-group's
  condition `"a"` no longer matches). Colliding rules are isolated into separate sub-groups,
  so the multi-pass loop can retry them if the source condition still matches in subsequent
  passes.
```

to:
```
- **D7 — `first_rule_wins` via token substitution dict.** When multiple rules in the same
  `(column_source, column_target)` group match the same source token, the first rule in join
  order wins. This is enforced by the token substitution dict using first-write-wins semantics:
  when a token already has a pending substitution, subsequent substitutions for that token are
  skipped. Groups are NOT decomposed — all rules in a `(column_source, column_target)` pair
  are processed together in a single vectorized pass. Example: target `"a; b; c"` with two
  rules `"a"` → `"A"` and `"a"` → `"AA"` yields `"A; b; c"` (the first rule's substitution
  for token `"a"` is applied; the second rule's substitution for the same token is skipped).
```

### 6b. `pipeline-behaviors.md` — D7 references

Update D7 references in other sections:

Line ~111, change:
```
  `last_rule_wins` strategy was replaced by `first_rule_wins` via group decomposition (D7).
```
to:
```
  `last_rule_wins` strategy was replaced by `first_rule_wins` via token substitution dict (D7).
```

Line ~149, change:
```
  D7 (group decomposition); nothing records them.
```
to:
```
  D7 (first-write-wins in token substitution dict); nothing records them.
```

Line ~165, change:
```
  later in rule order. D7's group decomposition governs collisions on *the same token*;
```
to:
```
  later in rule order. D7's first-write-wins governs collisions on *the same token*;
```

Line ~175, change:
```
  rules hit the same token, the first in rule order wins via group decomposition (D7) — there
```
to:
```
  rules hit the same token, the first in rule order wins via first-write-wins (D7) — there
```

### 6c. `design/first-rule-wins.md` (rewrite)

File: `.claude/docs/design/first-rule-wins.md`

Rewrite the document to describe first-write-wins instead of group decomposition.
Content outline:
- **Original problem**: `token_substitutions.setdefault(row_id, {})[token_value] = value`
  was last-write-wins, causing silent collision resolution on 8,571 rows.
- **First implementation (wrong)**: `_decompose_group()` expanded 15 groups → 810 sub-groups,
  causing 225x slowdown.
- **Final implementation**: first-write-wins in the substitution dict. A single check
  `if token_value not in subs` before writing. Zero group expansion, O(1) extra per
  substitution.
- **Semantics**: First rule in join order (determined by `__whep_rule_order__`) wins.
- **Data impact**: Same result as decomposition for collision cases, but with performance
  identical to the original (~93s for the full dataset).

### 6d. `deferred-bugs.md` (remove entry)

Remove the entry "First-rule-wins patch causes 225x performance regression via group
decomposition" from `.claude/docs/deferred-bugs.md`.

## Step 7: Validation

### 7a. Mandatory gates

```bash
py -3.14 -m pytest -q
py -3.14 -m ruff check .
py -3.14 -m mypy
```

### 7b. Performance benchmark

```python
import time, polars as pl
from pathlib import Path
from whep_digitize.postpro.rule_engine.schema_validation import build_conditional_rule_dictionary
from whep_digitize.postpro.rule_engine.conditional_group import apply_conditional_rule_group

f = Path('data/input/clean/clean_commodity.xlsx')
df = pl.read_excel(f, sheet_name='commodity_footnote')

# Verify no decomposition
groups = build_conditional_rule_dictionary(df, 'clean')
print(f'Groups: {len(groups)} (expected: 1)')

# Benchmark with 3,000 rows
dataset = pl.DataFrame({
    'commodity': ['cotton', 'rice', 'wheat'] * 1000,
    'footnotes': ['sea island; stripped', 'jasmine; basmati', 'durum; soft'] * 1000,
    'polity': ['us'] * 3000,
    'continent': ['north america'] * 3000,
    'unit': ['kg'] * 3000,
    'variable': ['prod'] * 3000,
    'year': [2000] * 3000,
    'value': [100.0] * 3000,
})

t0 = time.perf_counter()
result = apply_conditional_rule_group(
    dataset, group_rules=df, stage_name='clean',
    dataset_name='t', rule_file_id='t', execution_timestamp_utc='t'
)
elapsed = time.perf_counter() - t0
print(f'Time: {elapsed*1000:.0f}ms (expected: <100ms, was 10446ms with decomposition)')
```

### 7c. Verify first-rule-wins with colliding rules

```python
from whep_digitize.postpro.rule_engine.payload_application import apply_rule_payload

dataset = pl.DataFrame({
    'commodity': ['rice'],
    'unit': ['tok_a; b'],
})
rules = pl.DataFrame({
    'column_source': ['commodity', 'commodity'],
    'value_source_raw': ['rice', 'rice'],
    'column_target': ['unit', 'unit'],
    'value_target_raw': ['tok_a', 'tok_a'],
    'value_target': ['REPLACED_A', 'REPLACED_AA'],
})
result = apply_rule_payload(
    dataset, rules, 'clean', 'whep', 'rules', '2026-01-01T00:00:00Z'
)
print(f"Unit: {result.data.get_column('unit').to_list()}")
# Expected: ['REPLACED_A; b'] (first rule wins)
```

## What NOT to do

- **DO NOT** modify the logic of `apply_conditional_rule_group()` beyond docstrings
- **DO NOT** change `payload_application.py`
- **DO NOT** modify multi-pass logic in `layer_runner.py`
- **DO NOT** add caching or memoization
- **DO NOT** change the semantics of `#EXACT#`, `#ANY#`, or target condition matching
- **DO NOT** create new design files (update the existing ones)

## Acceptance criteria

1. ✅ All tests pass (`py -3.14 -m pytest -q`)
2. ✅ Ruff clean (`py -3.14 -m ruff check .`)
3. ✅ Mypy clean (`py -3.14 -m mypy`)
4. ✅ commodity_footnote benchmark with 3,000 rows: <100ms (was 46ms, with bug: 10,446ms)
5. ✅ `build_conditional_rule_dictionary()` returns ~15-17 groups for clean rules (not 810)
6. ✅ First-rule-wins is preserved: two rules with same `value_source_raw` → first wins
7. ✅ Grep for `decompose` returns no results in Python code
8. ✅ The `deferred-bugs.md` entry about performance regression is removed
