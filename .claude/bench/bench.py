"""Full-pipeline wall-clock benchmark — the autocode ``performance`` metric.

Runs the whole ``setup -> ingest -> postpro -> export`` pipeline over a frozen dataset and
prints ``PIPELINE_SECONDS: <n>`` (the minimum wall-clock over N iterations, so OS/GC jitter is
squeezed out). Progress is disabled and the run writes into a throwaway temp root, so the
benchmark is a pure, side-effect-free timing of the pipeline.

Dataset resolution (first match wins) — a real, sizeable dataset locally, a reproducible fallback
everywhere:

1. ``WHEP_BENCH_IMPORT_DIR`` — a ``data/import``-shaped tree (``raw`` / ``clean`` /
   ``standardize`` / ``harmonize`` subdirectories, any subset). Freeze a snapshot here for
   rigorous A/Bs, since the production dataset grows.
2. this project's own ``data/import`` when it holds raw workbooks — the real local optimization
   target.
3. the committed ``tests/fixtures/corpus`` (raw) + ``tests/fixtures/rule_files_postpro`` (clean /
   harmonize rules) — small but self-contained, and it exercises the multi-pass rule engine.

``WHEP_BENCH_ITERATIONS`` (default 3) sets the iteration count.

Run: ``.venv/Scripts/python.exe .claude/bench/bench.py``. Kept read-only by autocode
(see ``autocode.toml``).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from whep_digitize.pipeline import run_pipeline
from whep_digitize.setup.options import RuntimeOptions

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_IMPORT = _REPO_ROOT / "data" / "import"
_CORPUS = _REPO_ROOT / "tests" / "fixtures" / "corpus"
_RULES = _REPO_ROOT / "tests" / "fixtures" / "rule_files_postpro"

# Import layers copied from a resolved source tree, when present.
_LAYERS = ("raw", "clean", "standardize", "harmonize")


def _populate_import_tree(dst_import: Path) -> str:
    """Populate ``<dst_import>`` (a ``data/import`` dir) with the benchmark dataset.

    Returns a short label naming the resolved source, for the summary line.
    """
    env_dir = os.environ.get("WHEP_BENCH_IMPORT_DIR")
    if env_dir:
        source: Path | None = Path(env_dir)
    elif any(_LOCAL_IMPORT.glob("raw/**/*.xlsx")):
        source = _LOCAL_IMPORT
    else:
        source = None
    if source is not None:
        for layer in _LAYERS:
            if (source / layer).is_dir():
                shutil.copytree(source / layer, dst_import / layer)
        return f"import-dir:{source}"
    # Committed fallback: corpus raw + the postpro-stage rule fixtures (milk/date), so the
    # clean/harmonize multi-pass rule engine is actually exercised by the benchmark.
    shutil.copytree(_CORPUS, dst_import / "raw")
    shutil.copytree(_RULES / "clean", dst_import / "clean")
    shutil.copytree(_RULES / "harmonize", dst_import / "harmonize")
    return "fixtures-corpus"


def main() -> None:
    """Time the full pipeline over the resolved dataset and print ``PIPELINE_SECONDS``."""
    iterations = max(1, int(os.environ.get("WHEP_BENCH_ITERATIONS", "3")))
    options = RuntimeOptions(progress_enabled=False)

    tmp_root = Path(tempfile.mkdtemp(prefix="whep_bench_"))
    try:
        import_dir = tmp_root / "data" / "import"
        import_dir.parent.mkdir(parents=True, exist_ok=True)
        label = _populate_import_tree(import_dir)

        timings: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            run_pipeline(root=tmp_root, show_view=False, options=options)
            timings.append(time.perf_counter() - start)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    best = min(timings)
    print(f"# dataset={label} iterations={iterations} times={[round(t, 3) for t in timings]}")
    print(f"PIPELINE_SECONDS: {best:.4f}")


if __name__ == "__main__":
    main()
