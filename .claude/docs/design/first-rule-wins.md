# First-Rule-Wins via Token Substitution Dict

**Date:** 2026-09-09
**Status:** Implemented
**Related:** D7 in [pipeline-behaviors.md](../pipeline-behaviors.md)

## Problem

The rule engine previously used `last_rule_wins` collision resolution. When two rules in the same
`(column_source, column_target)` group matched the same source token but had different target
conditions, both rules fired simultaneously (cartesian join), and the last write to the
`token_substitutions` dict won. This silently resolved ~8,571 conflicting substitutions with no
diagnostic.

## First Implementation (Wrong)

The first fix attempted group decomposition via `_decompose_group()` in `schema_validation.py`.
It split colliding groups into single-rule sub-groups, expanding 15 groups → 810 sub-groups (54x).
Each sub-group executed the full `apply_conditional_rule_group()` pipeline (explode, normalize,
join, sort, target match), repeating O(N) work 54x times.

**Benchmark:** clean_commodity.xlsx (768 rules, 1 group → 718 sub-groups): 46ms → 10,446ms (225x)
with 3,000 rows. Extrapolated to the real dataset (794K rows): ~46 min for that file alone.

Python overhead (~14.5ms/sub-group) dominated total time. Full analysis:
`performance-regression-first-rule-wins.md`.

## Final Implementation

First-write-wins in the token substitution dict. A single check `if token_value not in subs`
before writing. Zero group expansion, O(1) extra per substitution.

### Mechanism

In `_apply_source_rewrite()` and `_apply_target_token_rewrite()` (conditional_group.py), the
token substitution loop checks whether a token already has a pending substitution before writing:

```python
subs = token_substitutions.setdefault(row_id, {})
if token_value not in subs:
    subs[token_value] = value
```

The join is sorted by `__whep_rule_order__`, so loop iterations come in rule order. If a token
already has a substitution, skipping the new one means the first rule in order wins.

### Example

Rules in group `(commodity, unit)`:
- Rule A: commodity=x, unit=a → unit=A
- Rule B: commodity=x, unit=a → unit=AA

**Before (last_rule_wins):** Both rules fire simultaneously. Last write wins: unit = "AA".

**After (first_rule_wins):** Both rules are in the same group, processed in a single vectorized
pass. Rule A's substitution for token "a" is applied first; Rule B's substitution for the same
token is skipped. Result: unit = "A".

### Semantics

First rule in join order (determined by `__whep_rule_order__`) wins. Groups are NOT decomposed —
all rules in a `(column_source, column_target)` pair are processed together. The multi-pass loop
still retries across passes if the source condition still matches.

### Cycle detection

With first-write-wins, oscillating rules (a→b, b→a) that share `value_source_raw` are in the
same group. Only one rule's target condition matches per pass, so the oscillation happens across
passes rather than within a pass. The cycle detection correctly identifies this as a cycle
(repeated state) rather than convergence.

## Implementation

- **`schema_validation.py`:** Removed `_decompose_group()`. `build_conditional_rule_dictionary()`
  returns one group per `(column_source, column_target)` pair without decomposition.
- **`conditional_group.py`:** First-write-wins in `_apply_source_rewrite()` and
  `_apply_target_token_rewrite()` via `if token not in subs` check.
- **Tests:** Updated to reflect no decomposition and first-write-wins semantics.

## Impact

- Same result as decomposition for collision cases.
- Performance identical to pre-decomposition (~93s for full dataset).
- ~8,571 rows in the real dataset have different values compared to last-write-wins.
- No diagnostic is emitted for the discarded candidates (D9).

## Testing

- All tests pass, including parity tests.
- Benchmark: commodity_footnote with 3,000 rows: <100ms (was 46ms baseline, 10,446ms with bug).
