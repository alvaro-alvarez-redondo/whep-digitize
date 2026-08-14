---
name: testing
description: Generate or refactor pytest tests for Python modules.
---

# Testing

Every behavior/contract change ships with tests. Use `pytest`. Required types: happy path,
edge case, error case, and — when the change affects pipeline output — a **parity** test against
the frozen reference goldens (`@pytest.mark.parity`).

- Deterministic: no network/filesystem side effects; use `tmp_path` + the `conftest.py`
  fixtures (`project_dir`, `config`, `sample_long_df`); seed randomness.
- Compare frames with `polars.testing.assert_frame_equal` (set `check_dtypes` deliberately —
  data is string-typed until the postpro audit step).
- Cover the edge cases that bite: empty input, all-null columns, unicode/accented strings
  (normalization), duplicate rows, wildcard `#ANY#`, null↔null matching.
- Mark long/full-dataset tests `@pytest.mark.slow`.

Run the full suite via `.venv/Scripts/python.exe -m pytest -q` (see
[conventions.md](../docs/conventions.md)). **Never accept a change that lowers pass rate.**
