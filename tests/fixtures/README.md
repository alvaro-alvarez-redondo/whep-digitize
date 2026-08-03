# Test fixtures — the frozen corpus

Fixed inputs for the test suite. **Committed and immutable**: the frozen reference outputs under
`tests/golden/` correspond to *these exact bytes*. Editing a fixture invalidates every golden
derived from it, so treat both as one unit — see `tests/golden/README.md`.

## `corpus/` — real raw workbooks

A small representative subset of real raw import workbooks. The directory layout mirrors a real
import root (`<yearbook>/<yearbook>_<category>/<file>.xlsx`), so `corpus/` is a drop-in
raw-import root for ingest-stage tests. One smallest-available workbook per data category was
chosen to span the ingest surface while keeping the committed binary footprint tiny
(~37 KB total):

| Category   | File |
|------------|------|
| crops      | `fao_1949/fao_1949_crops/r_fao_1949_crops_92_92_date.xlsx` |
| livestock  | `fao_1949/fao_1949_livestock/r_fao_1949_livestock_162_162_milk.xlsx` |
| population | `fao_1949/fao_1949_population/r_fao_1949_population_24_24_population_agriculture.xlsx` |
| inputs     | `fao_1955/fao_1955_inputs/r_fao_1955_inputs_228_229_pesticide_fluoride.xlsx` |
| land       | `fao_1952/fao_1952_land/r_fao_1952_land_3_9_irrigation_permanent_meadows_pastures.xlsx` |
| trade      | `fao_1950/fao_1950_trade/r_fao_1950_trade_106_106_palm_kernel_oil.xlsx` |

## `synthetic/` — edge-case fixtures

Tiny hand-authored fixtures that force the edge cases real workbooks may not contain.

### `file_metadata_inputs.json`

A JSON array of file-path strings fed to `extract_file_metadata`
(`ingest/file_io/metadata.py`). The first six are the real `corpus/` workbook paths
(relative, forward-slash); the rest force the positional-parsing edge cases:

| Edge case                         | Element |
|-----------------------------------|---------|
| real corpus paths (basename via `path_file`) | the six `tests/fixtures/corpus/.../*.xlsx` |
| `<=6` tokens → no commodity       | `r_fao_1961_crops_1_1.xlsx` |
| no 4-digit token → no yearbook    | `r_fao_crops_wheat.xlsx` |
| `<2` tokens → no yearbook         | `2020.xlsx` |
| first 4-digit token wins          | `r_fao_1961_a_b_c_2000_wheat.xlsx` → yearbook `fao_1961`, commodity `2000_wheat` |
| non-ASCII name (`is_ascii` false + error message) | `r_fao_1949_a_b_c_wheat_café.xlsx` |

### `header_names_inputs.json`

A JSON array of raw header names fed to `normalize_header_names`
(`ingest/reading/header_normalization.py`). Exercises the ordered regex chain and the NFD
diacritic-strip fold on accented/unicode headers. Because the header non-alnum pattern **keeps**
`/` (unlike match-key normalization), it also surfaces folds masked elsewhere. Characters with no
ASCII base (`groß`, `½`, `œuvre`, `æ`, `ø`) are covered by the policy tests in
`tests/setup/test_helpers.py` rather than here.

| Edge case                | Element(s) |
|--------------------------|------------|
| accents / diacritics     | `café au lait`, `São Paulo`, `Côte d'Ivoire`, `Zürich`, `Ñoño`, `naïve`, `Åland`, `Región`, `Población` |
| separator padding        | `Year / Period`, `value - amount`, `p - q / r` |
| punctuation → underscore | `GDP  (current US$)`, `value %`, `a,b;c`, `test@#123` |
| underscore collapse/trim | `a__b`, `_leading_`, `__x__` |
| empty / null / fast-path | `""`, `null`, `continent`, `hemisphere`, `a-b`, `x/y` |

## Verifying

    .venv/Scripts/python.exe -m pytest -m parity
