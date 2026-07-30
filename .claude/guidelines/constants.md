---
name: constants
description: Centralize hard-coded literals into the constants module.
---

# Constants

Scan for paths, thresholds, regexes, magic numbers, repeated strings. Move them into
`src/whep_digitize/setup/constants.py` (the relevant frozen dataclass group) and reference
via `get_pipeline_constants()`. Add new groups as frozen dataclasses; sequences as tuples,
mappings as `MappingProxyType` (immutability is enforced).

Runtime-toggleable behavior goes in `RuntimeOptions` (`setup/options.py`), not constants.
Remove backward-compat scaffolding. Keep tests (`tests/setup/test_constants.py`) and
[constants-and-options.md](../docs/constants-and-options.md) in sync. Preserve the public
`get_pipeline_constants()` surface. Deterministic behavior only.
