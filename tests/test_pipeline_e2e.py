"""End-to-end integration test for the top-level ``run_pipeline`` orchestrator.

Exercises the full ``setup -> ingest -> postpro -> export`` wiring over the committed fixture
corpus + postpro rule fixtures (so the multi-pass rule engine fires), asserting a valid
:class:`OutputResult` with the processed-data TSV and the per-column unique-list workbooks
written to disk. Stage- and module-level *parity* (vs the frozen reference) is covered by
``tests/parity/`` — this guards the orchestration glue itself (which those stage tests bypass),
and full-pipeline byte-parity over the frozen dataset is verified out-of-band (see
``.claude`` docs / ``.claude/bench``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl

from whep_digitize.contracts import OutputResult
from whep_digitize.pipeline import run_pipeline
from whep_digitize.setup.options import RuntimeOptions

_FIXTURES = Path(__file__).parent / "fixtures"
_LONG_COLUMNS = [
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "value",
    "notes",
    "footnotes",
    "yearbook",
    "document",
]


def _assemble_input_tree(root: Path) -> None:
    """Lay out ``<root>/data/input`` = fixture corpus (raw) + postpro rule fixtures."""
    input_dir = root / "data" / "input"
    input_dir.mkdir(parents=True)
    shutil.copytree(_FIXTURES / "corpus", input_dir / "raw")
    shutil.copytree(_FIXTURES / "rule_files_postpro" / "clean", input_dir / "clean")
    shutil.copytree(_FIXTURES / "rule_files_postpro" / "harmonize", input_dir / "harmonize")


def test_run_pipeline_end_to_end(tmp_path: Path) -> None:
    _assemble_input_tree(tmp_path)

    result = run_pipeline(
        root=tmp_path,
        options=RuntimeOptions(progress_enabled=False, ingest_parallel_workers=1),
    )

    assert isinstance(result, OutputResult)

    # Processed data: one TSV per layer, each written + non-empty with the canonical header.
    assert sorted(result.processed_paths) == [
        "whep_data_clean",
        "whep_data_harmonize",
        "whep_data_normalize",
        "whep_data_raw",
    ]
    for tsv in result.processed_paths.values():
        assert tsv.is_file() and tsv.stat().st_size > 0
        lines = tsv.read_text(encoding="utf-8").splitlines()
        assert lines[0].split("\t") == _LONG_COLUMNS
        assert len(lines) > 1  # header + at least one data row

    # Per-column unique-list workbooks: all written and non-empty.
    assert result.lists_paths
    for path in result.lists_paths.values():
        assert path.is_file() and path.stat().st_size > 0


def test_run_pipeline_e2e_deterministic(tmp_path: Path) -> None:
    """Same inputs -> byte-identical processed TSV (the pipeline's determinism guarantee)."""
    options = RuntimeOptions(progress_enabled=False, ingest_parallel_workers=1)

    first_root = tmp_path / "run_a"
    first_root.mkdir()
    _assemble_input_tree(first_root)
    first = run_pipeline(root=first_root, options=options)
    first_tsv = first.processed_paths["whep_data_harmonize"].read_bytes()

    second_root = tmp_path / "run_b"
    second_root.mkdir()
    _assemble_input_tree(second_root)
    second = run_pipeline(root=second_root, options=options)
    second_tsv = second.processed_paths["whep_data_harmonize"].read_bytes()

    assert first_tsv == second_tsv
    # Parses back to a non-empty frame with the canonical schema (all-text read, no inference).
    frame = pl.read_csv(
        first.processed_paths["whep_data_harmonize"], separator="\t", infer_schema_length=0
    )
    assert frame.columns == _LONG_COLUMNS
    assert frame.height > 0
