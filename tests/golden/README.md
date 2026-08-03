# Golden outputs — the frozen reference

Frozen expected outputs of the pipeline over the frozen inputs in `tests/fixtures/`.
`tests/parity/test_*_parity.py` asserts the pipeline still reproduces them exactly. Layout:
`tests/golden/<module>/<export>.json`, one directory per entry in `tests/parity/goldens.py`.

## Immutable, and committed on purpose

These files **are committed**, which is what lets the parity suite run on any checkout — CI
included. They are the project's strongest regression signal: they pin observable output rather
than implementation detail.

**There is no regeneration path.** A golden changes only through a deliberate, reviewed edit, in
the same change that intentionally moves the behavior — and then
`.claude/docs/pipeline-behaviors.md` is updated to match. A golden diff in a PR that did not
intend to change output is a regression, not a refresh.

After any intentional edit, verify:

    .venv/Scripts/python.exe -m pytest -m parity

## Why a presence guard exists

Every parity test `pytest.skip`s when its golden is missing, so an absent golden set would make
the parity suite pass while comparing nothing. `tests/parity/test_goldens_present.py` fails
loudly in that situation, per module.

## Format, and why JSON

Each export is a JSON array of strings (or `null`) — the one format that round-trips the
null-vs-`""` distinction the pipeline's match keys hinge on. See `tests/parity/goldens.py`.

## The one platform-relative golden

`export_processed_data/tsv_hex.json` is the exact bytes of a whole processed TSV, hex-encoded.
The writer uses the **platform** newline (`\r\n` on Windows, `\n` elsewhere), so that golden's
record separators belong to whichever OS produced it — currently Windows, while CI runs Linux.

`test_export_processed_data_parity.py` handles this by re-terminating the golden's records (and
only those — never a newline embedded in a quoted field) with the eol the *current* platform
would use, derived independently of the code under test. The comparison stays byte-exact and
still pins the eol convention.

`.gitattributes` marks this directory `-text` so no `core.autocrlf` setting can rewrite these
bytes in transit.
