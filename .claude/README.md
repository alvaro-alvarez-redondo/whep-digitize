# Claude layer

Start at [CLAUDE.md](../CLAUDE.md) (auto-loaded). Files here are read on demand.

## Structure

- `docs/`
  - [architecture.md](docs/architecture.md) — stages, data flow, entry points, contracts.
  - [codebase-map.md](docs/codebase-map.md) — where every function lives. Use instead of grepping.
  - [pipeline-behaviors.md](docs/pipeline-behaviors.md) — the **intentional** behaviors that look
    like bugs. Read before changing pipeline semantics.
  - [constants-and-options.md](docs/constants-and-options.md) — the constants surface and
    `WHEP_*` runtime options.
  - [conventions.md](docs/conventions.md) — run/test, environment, determinism, gotchas.
  - [common-changes.md](docs/common-changes.md) — task recipes. **Check here first.**
  - [deferred-bugs.md](docs/deferred-bugs.md) — known bugs left unfixed, and when to revisit.
- `guidelines/` — refactoring, performance, testing, constants.
- `commands/autocode.md` — the `/autocode` optimization loop.
- `progress.md` + `results.tsv` — autocode session state.
- `bench/bench.py` — full-pipeline wall-clock benchmark.

Most-used pair: **[codebase-map.md](docs/codebase-map.md)** to find code, and
**[pipeline-behaviors.md](docs/pipeline-behaviors.md)** before changing what it does.

Plain Markdown with optional `name`/`description` frontmatter.
