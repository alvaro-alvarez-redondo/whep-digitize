# Full-dataset parity

How the Python port is verified against R on the **real** dataset — as opposed to the
6-workbook fixture corpus the routine test suite uses. Read
[architecture.md](architecture.md) → *Datasets* first for the distinction between the two.

## Why this exists

Automated parity used to stop at the fixture corpus (6 workbooks, committed, R-free in CI). The
full-dataset R-vs-Python byte diff was an **unversioned manual procedure** — run R, copy the
inputs to a temp root, run Python, eyeball the diffs — so nothing guarded it, nothing recorded
its result, and it silently stopped being run. `scripts/parity_full_dataset.py` is that procedure
turned into a script that exits non-zero when parity breaks.

## Precondition: R is the oracle

There is no reference output without running R. The harness therefore **requires** all three of:

| Requirement | Default location | Override |
|---|---|---|
| The sibling R project | `../whep-digitalization` | `--r-project`, `WHEP_R_PROJECT` |
| An executable R | `C:/Program Files/R/R-4.6.0` | `WHEP_R_HOME`, or `Rscript` on `PATH` |
| The full raw dataset | `<r-project>/data/1-import/10-raw_import` | (comes with the R project) |

When any is missing the harness exits **2** with an explanatory message. It never degrades to a
silent pass — a parity check that cannot reach its oracle has not verified anything.

## Running it

```bash
.venv/Scripts/python.exe scripts/parity_full_dataset.py
```

That reuses the R project's existing `data/3-export` output and refuses to run if it is older
than the newest input workbook (override with `--allow-stale-r-output`). To regenerate the
reference first:

```bash
.venv/Scripts/python.exe scripts/parity_full_dataset.py --run-r
```

`--run-r` executes the R project's documented entry point (`whep-digitalization.R`) and
therefore **overwrites that project's `data/2-postpro` and `data/3-export`**. It is opt-in for
exactly that reason.

Other flags: `--divergence-budget N` (default 13), `--keep-output` (keep the staged Python run
for inspection). Exit codes: `0` parity, `1` parity failure, `2` precondition failure.

The same check is exposed as `tests/parity/test_full_dataset_parity.py`, marked
`@pytest.mark.slow` and excluded from the default suite (`addopts = -m "not slow"`):

```bash
.venv/Scripts/python.exe -m pytest -m slow
```

It **fails** rather than skips when the oracle is absent — it is opt-in, so a silent skip would
defeat its purpose. The classifier logic in the same file is pure and runs in the default suite.

## What it compares

The Python pipeline runs via `run_pipeline(root=<temp>)` over inputs staged from the R project
(R's `10-raw_import`/`11-clean_import`/… mapped onto `raw`/`clean`/…), so neither project's
working tree is touched.

* **Processed TSVs — byte-level.** Byte-identical, or else classified row by row.
* **Unique-list workbooks — content-level** (sheet names + cell values). Raw-byte identity is
  unachievable across R `writexl` and Python `xlsxwriter`, which use different ZIP writers.

## How differences are judged

**Rows are compared as multisets, never positionally.** This is the one design decision that
matters. An accepted divergence rewrites a *sort key* — `philippines r` and `philippines` sort to
different places — so every subsequent row shifts and a line-by-line diff degenerates into tens
of thousands of meaningless pairings, some of which coincidentally *look* like valid divergences
(`'lemon lime'` → `'lemon'` passes a subsequence test but is two unrelated rows). Multiset
differencing reduces the real signal here from 22,067 spurious findings to 16 genuine ones.

The leftover rows are then classified:

* **Processed TSVs are record-valued** → rows must pair **1:1** (maximum bipartite matching).
  Two R rows collapsing onto one Python row is a defect.
* **Unique lists are set-valued** → an accepted divergence may legitimately **collapse** two R
  entries into one Python entry, so the sheet has fewer rows. A row is accepted if it differs by
  the accepted shape from *any* row on the other side.

A pair counts as an **accepted divergence** only when every differing field passes:

1. the field is **not** `year` or `value` — an accepted divergence never touches those; and
2. the Python value is reachable from the R value **by deleting characters**.

Rule 2 is the discriminator. The policy drops exactly the characters ICU expands or maps
(`(R)` for `®`, `1/2` for `½`, `ss` for `ß`, `ae` for `æ`), so Python's string is always a
subsequence of R's. A wrong join, a shifted field or a dropped record effectively never satisfies
it. Blanking a non-empty value is rejected outright — the subsequence relation holds trivially
for the empty string, which would otherwise excuse a whole class of real defects.

Independently enforced: identical row counts, identical headers, identical line terminators, and
an exact `Decimal` **`value` sum**.

## Measured state — 2026-07-31, 1,339 workbooks, 592,719 rows

**Accepted (13 rows, exactly the documented budget)** — all `polity`, all the ICU `®` → ` (R)`
expansion the policy drops. The docs previously named only two of the five affected polities:

| R | Python | rows |
|---|--------|------|
| `philippines r` | `philippines` | 4 |
| `uruguay r` | `uruguay` | 4 |
| `nicaragus r` | `nicaragus` | 2 |
| `brazil r` | `brazil` | 2 |
| `australia r` | `australia` | 1 |

`unique_polity.xlsx` correspondingly has 5 fewer rows (3,939 vs 3,944) — the five R values
collapse onto entries Python already had. The other 9 unique-list workbooks are
content-identical.

**Rejected: 0 rows.** The `value` sums are exactly equal (`Decimal` compare), as are row counts,
headers and line terminators.

**So the harness exits 0.** The only differences left are the 13 accepted policy rows.

### The one defect this harness caught (DB3, fixed 2026-07-31)

The first run (2026-07-30) rejected **3 rows** in `r_iia_1938_trade_666_673_cotton.xlsx` where R
wrote `99.9999999999996` / `199.999999999999` and Python wrote `100` / `200`, a `value`-sum gap of
1.8E-12 out of 9.29E12. It was logged as DB3 and, on the evidence then available, read as R
carrying ~28 ulps of accumulated error in the unit conversion.

**That diagnosis was wrong, and the harness was right to reject it.** The workbook stores
`0.09999999999999964` and `0.1999999999999993` (spreadsheet subtraction artefacts) in a
`1000 quintals` column. readxl's `col_types = "text"` renders the shortest string that
round-trips each double, so R multiplied the stored value; **calamine's text coercion rounds to
about 12 significant digits**, so Python multiplied `0.1`. Python was not more accurate — it had
silently discarded source precision at the ingest read, and the `x1000` unit standardization
amplified the loss above the 15-significant-digit rendering threshold.

The fix is in `ingest/reading/sheet_read.py`: each sheet is read twice (all-as-text, then with
dtype inference) and `restore_numeric_text_precision` rewrites **only** the text cells that fail
to parse back to the exact stored number. Cells calamine rendered faithfully pass through
byte-for-byte, so no golden moved. Cost: the full-dataset run went from ~11s to ~14s.

The bug class is wider than those 3 rows — a sample of 120 workbooks holds 2 further lossy cells
whose error stays below the rendering threshold, so they never surfaced as a diff. The repair
fixes those silently too.
