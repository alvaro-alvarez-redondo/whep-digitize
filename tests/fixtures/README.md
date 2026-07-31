# Test fixtures — the frozen parity corpus

Fixed inputs for R→Python parity checks. **Committed and immutable**: the R golden outputs
under `tests/golden/` (committed alongside them) are captured from *these exact bytes*, so a
Python port is compared against R on identical inputs. Do not edit a fixture without
re-capturing the affected goldens (`python tests/parity/capture.py <module>`) and committing
both halves together.

## `corpus/` — real raw workbooks

A small representative subset of the R project's raw import workbooks, copied verbatim from

    <whep-digitalization>/data/1-import/10-raw_import/

The directory layout mirrors the source (`<yearbook>/<yearbook>_<category>/<file>.xlsx`), so
`corpus/` is a drop-in raw-import root for ingest-stage (Stage 1) parity captures — the
`sheet_read` capture reads `fao_1949/fao_1949_crops/r_fao_1949_crops_92_92_date.xlsx` directly
(via the harness `fixtures_dir` + `preamble`), so R and Python read identical bytes. One
smallest-available workbook per data category was chosen to span the ingest surface while
keeping the committed binary footprint tiny (~37 KB total):

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

A JSON array of file-path strings fed to `extract_file_metadata` (`10-metadata.R` →
`ingest/file_io/metadata.py`). The first six are the real `corpus/` workbook paths
(relative, forward-slash); the rest force the positional-parsing edge cases:

| Edge case                         | Element |
|-----------------------------------|---------|
| real corpus paths (basename via `path_file`) | the six `tests/fixtures/corpus/.../*.xlsx` |
| `<=6` tokens → no commodity       | `r_fao_1961_crops_1_1.xlsx` |
| no 4-digit token → no yearbook    | `r_fao_crops_wheat.xlsx` |
| `<2` tokens → no yearbook         | `2020.xlsx` |
| first 4-digit token wins          | `r_fao_1961_a_b_c_2000_wheat.xlsx` → yearbook `fao_1961`, commodity `2000_wheat` |
| non-ASCII name (`is_ascii=FALSE` + error message) | `r_fao_1949_a_b_c_wheat_café.xlsx` |

### `header_names_inputs.json`

A JSON array of raw header names fed to `normalize_header_names` (`11-header-normalization.R`
→ `ingest/reading/header_normalization.py`). Exercises the ordered regex chain and the
policy's NFD diacritic-strip transliteration on accented/unicode headers. Because the header
non-alnum pattern **keeps** `/` (unlike match-key normalization), it also surfaces
transliterations masked elsewhere. Only common-accent cases (where the policy and R's ICU
agree) live here; ICU-divergent inputs (`groß`, `½`, `œuvre`, `æ`, `ø`) are covered by the
policy tests in `tests/setup/test_helpers.py`, not this R-parity fixture.

| Edge case                | Element(s) |
|--------------------------|------------|
| accents / diacritics     | `café au lait`, `São Paulo`, `Côte d'Ivoire`, `Zürich`, `Ñoño`, `naïve`, `Åland`, `Región`, `Población` |
| separator padding        | `Year / Period`, `value - amount`, `p - q / r` |
| punctuation → underscore | `GDP  (current US$)`, `value %`, `a,b;c`, `test@#123` |
| underscore collapse/trim | `a__b`, `_leading_`, `__x__` |
| empty / null / fast-path | `""`, `null`, `continent`, `hemisphere`, `a-b`, `x/y` |

Every input here folds identically under R's ICU `Latin-ASCII` and the port's NFD diacritic
strip, which is why an R golden can still pin this module (verified in
`tests/parity/test_header_normalization_parity.py`).

## Regenerating goldens

Goldens are derived from these fixtures via the R source of truth:

    .venv/Scripts/python.exe tests/parity/capture.py            # all modules
    .venv/Scripts/python.exe tests/parity/capture.py file_metadata

Then verify the Python port matches:

    .venv/Scripts/python.exe -m pytest -m parity
