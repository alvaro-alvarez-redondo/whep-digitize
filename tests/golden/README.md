# Golden outputs — the frozen R reference

The captured outputs of the R source of truth (`whep-digitalization`), run over the frozen
inputs in `tests/fixtures/`. `tests/parity/test_*_parity.py` asserts the Python port reproduces
them. Layout: `tests/golden/<module>/<export>.json`, one directory per `CAPTURES` entry in
`tests/parity/registry.py`.

## Committed on purpose

These files **are committed** (they were gitignored until parity was wired into CI). They are
versioned build artifacts of a frozen upstream: the R port is complete, so the reference does
not move, and committing it is what lets the parity suite run on any checkout — CI included —
with no R install and no `whep-digitalization` clone.

That is the whole point. Every parity test `pytest.skip`s when its golden is missing, so an
absent golden set makes the parity suite pass while comparing nothing; CI was green on a
checkout where no parity assertion ever executed. `tests/parity/test_goldens_present.py` now
fails loudly instead.

Do not hand-edit a golden. Regenerate it, from R, on a deliberate R-reference change only:

    .venv/Scripts/python.exe tests/parity/capture.py            # all modules
    .venv/Scripts/python.exe tests/parity/capture.py file_metadata

then verify and commit the diff together with the change that motivated it:

    .venv/Scripts/python.exe -m pytest -m parity

A golden diff in a PR that did not intend to move the R reference is a regression, not a
refresh.

## Format, and why JSON

Each export is a JSON array of strings (or `null` for R `NA`) — the one format that round-trips
the `NA`-vs-`""` distinction the pipeline's match keys hinge on. See `tests/parity/r_harness.py`.

## The one platform-relative golden

`export_processed_data/tsv_hex.json` is the exact bytes of a whole TSV written by
`data.table::fwrite`, hex-encoded. `fwrite` uses the **platform** newline (`\r\n` on Windows,
`\n` on unix) and the port mirrors it, so that golden's record separators belong to whichever OS
captured it — currently Windows, while CI runs Linux.

`test_export_processed_data_parity.py` handles this by re-terminating the golden's records (and
only those — never a newline embedded in a quoted field) with the eol the *current* platform's
`fwrite` would use, derived independently of the code under test. The comparison stays
byte-exact and still pins the eol convention. Consequence: this golden may be recaptured on
either OS without invalidating the test.

`.gitattributes` marks this directory `-text` so no `core.autocrlf` setting can rewrite these
bytes in transit.
