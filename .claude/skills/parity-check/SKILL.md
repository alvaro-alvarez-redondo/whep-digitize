---
name: parity-check
description: >-
  Generate golden output from the R pipeline and verify the Python port reproduces it.
  Use when validating a migrated module or stage against whep-digitalization, capturing R
  golden files, or debugging a Python-vs-R output difference.
---

# parity-check

Establish and verify byte-level output parity between the R source of truth and the Python
port. Two modes: **capture** (produce R golden files) and **compare** (assert Python matches).

## Environment

- R lives at `C:/Program Files/R/R-4.6.0/` — invoke `Rscript.exe` (not on PATH here; use the
  full path or the launcher pattern noted in the R repo's memory).
- R source repo: `C:/Users/Usuario/Nextcloud/whep_alvaro/digitalization/whep-digitalization/`.
- Goldens live under `tests/golden/<module>/` in this repo (gitignored — regenerable).

## Capture (produce goldens)

1. Pick fixtures that exercise the module's edge cases (empty, accented, duplicates,
   wildcard, NA). Reuse the R repo's `tests` fixtures where possible.
2. Write a **temporary** R harness that sources the R stage helpers, runs the target
   function on each fixture, and writes outputs deterministically:
   - frames → `data.table::fwrite(x, file, sep="\t")` (or `.parquet` via `arrow` if dtypes
     matter).
   - scalars / error vectors → a text file, one value per line, in the R order.
3. Run it with `Rscript.exe` (script file, not `-e` — inline `-e` with data.table can
   segfault on this host). Save outputs to `tests/golden/<module>/`.
4. **Delete the temporary R harness immediately** (temp-file policy).

## Compare (verify Python)

1. Load the golden with polars (`pl.read_csv(..., separator="\t", infer_schema_length=0)`
   for string-typed stages; `read_parquet` when dtypes are checked).
2. Run the Python function on the same fixtures.
3. Assert with `polars.testing.assert_frame_equal`:
   - set `check_dtypes` deliberately — data is string-typed until the postpro audit step;
   - for error/diagnostic strings compare exact text **and** order when a consumer depends on it.
4. Wire it into the module's test file as a `@pytest.mark.parity` test so it runs in CI.

## When they differ

- Isolate the first differing row/column. Common causes, in likelihood order: normalization
  (policy NFD diacritic strip vs R's ICU `Latin-ASCII` — divergence on symbols / ligatures /
  non-decomposable letters is EXPECTED, not a bug), sort/tie ordering, null vs empty-string,
  float formatting, `melt`/`unpivot` dropped columns.
- Prefer matching R exactly, EXCEPT where a documented policy deliberately diverges (e.g.
  normalization — see [r-to-python-mapping.md](../../docs/r-to-python-mapping.md)); pin those
  with a policy test rather than an R golden. Never add a character-specific override to force
  ICU parity.
