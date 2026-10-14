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
    "iso_whep",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "value",
    "notes",
    "footnotes",
    "yearbook",
    "file",
]
# In the frozen fixture corpus, no rule ever populates `hemisphere` and no row carries a
# `notes` value, so both come out entirely null in every layer. The export stage drops an
# all-null column (`drop_all_null_columns`), so neither reaches any of the four TSVs.
_EXPECTED_EXPORT_COLUMNS = [c for c in _LONG_COLUMNS if c not in {"hemisphere", "notes"}]


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

    # Processed data: one TSV per layer, each written + non-empty with the canonical header
    # minus the columns this fixture corpus leaves entirely null (see
    # `_EXPECTED_EXPORT_COLUMNS`).
    assert sorted(result.processed_paths) == [
        "whep_data_clean",
        "whep_data_harmonize",
        "whep_data_normalize",
        "whep_data_raw",
    ]
    for tsv in result.processed_paths.values():
        assert tsv.is_file() and tsv.stat().st_size > 0
        lines = tsv.read_text(encoding="utf-8").splitlines()
        assert lines[0].split("\t") == _EXPECTED_EXPORT_COLUMNS
        assert len(lines) > 1  # header + at least one data row

    # Per-column unique-list workbooks: all written and non-empty.
    assert result.lists_paths
    for path in result.lists_paths.values():
        assert path.is_file() and path.stat().st_size > 0


def test_replace_directive_overrides_a_populated_cell_through_the_whole_pipeline(
    tmp_path: Path,
) -> None:
    """``#REPLACE#`` in a real rule file overwrites a cell whatever it holds, end to end.

    Ingest seeds ``iso_whep`` with ``"iso-" + year``, so the cell is already populated (and
    differs by year) when the harmonize stage replaces it with ``#REPLACE#``. That is the case
    an ordinary or blank condition cannot express, and it exercises the rule-file loader,
    multi-pass convergence (the replace rule fires on every pass but changes nothing after the
    first) and the stage chain together.
    """
    _assemble_input_tree(tmp_path)
    inputs = tmp_path / "data" / "input"
    (inputs / "harmonize" / "harmonize_iso_whep.csv").write_text(
        "harmonize_column_source,harmonize_value_source_raw,harmonize_value_source,"
        "harmonize_column_target,harmonize_value_target_raw,harmonize_value_target\n"
        "polity,albania,albania,iso_whep,#REPLACE#,alb-1912-1944\n",
        encoding="utf-8",
    )

    result = run_pipeline(
        root=tmp_path,
        options=RuntimeOptions(progress_enabled=False, ingest_parallel_workers=1),
    )

    def albania_codes(layer: str) -> list[str | None]:
        frame = pl.read_csv(
            result.processed_paths[f"whep_data_{layer}"], separator="\t", infer_schema_length=0
        )
        albania = frame.filter(pl.col("polity") == "albania")
        assert albania.height > 0
        return albania.get_column("iso_whep").unique().to_list()

    seeded = albania_codes("clean")
    # The ingest year tags (never null: every fixture row has a year).
    assert seeded and all(code is not None and code.startswith("iso-") for code in seeded)
    assert albania_codes("harmonize") == ["alb-1912-1944"]  # all replaced, not appended


def test_file_column_holds_the_source_workbook_name_in_every_export(tmp_path: Path) -> None:
    """The provenance column is ``file`` (it was ``document``) and holds each workbook's name.

    Pins the rename end to end: the column is created at ingest from the source file name, so
    every exported layer carries it, no ``document`` column survives anywhere, and its unique
    list is written as ``unique_file.xlsx``.
    """
    _assemble_input_tree(tmp_path)

    result = run_pipeline(
        root=tmp_path,
        options=RuntimeOptions(progress_enabled=False, ingest_parallel_workers=1),
    )

    for object_name, tsv in result.processed_paths.items():
        frame = pl.read_csv(tsv, separator="\t", infer_schema_length=0)
        assert "document" not in frame.columns, f"{object_name} still has a document column"
        files = frame.get_column("file").unique().to_list()
        assert files, f"{object_name}: file column is empty"
        assert all(name.endswith(".xlsx") for name in files), files
    assert "file" in result.lists_paths and "document" not in result.lists_paths
    assert result.lists_paths["file"].name == "unique_file.xlsx"


def test_run_pipeline_drops_all_null_columns_from_every_layer(tmp_path: Path) -> None:
    """The export stage prunes columns that came out entirely null, per layer.

    Pins the wiring explicitly rather than leaving it implicit in the header assertion above:
    `hemisphere`/`notes` are absent everywhere, and every other canonical column survives.
    """
    _assemble_input_tree(tmp_path)

    result = run_pipeline(
        root=tmp_path,
        options=RuntimeOptions(progress_enabled=False, ingest_parallel_workers=1),
    )

    for object_name, tsv in result.processed_paths.items():
        columns = pl.read_csv(tsv, separator="\t", infer_schema_length=0).columns
        assert "hemisphere" not in columns, f"{object_name} kept an all-null column"
        assert "notes" not in columns, f"{object_name} kept an all-null column"
        assert set(columns) == set(_EXPECTED_EXPORT_COLUMNS), (
            f"{object_name} dropped a column it shouldn't have, or kept an unexpected one"
        )


def test_iso_whep_is_seeded_at_ingest_and_rewritten_by_a_rule_file(tmp_path: Path) -> None:
    """``iso_whep`` starts as ``"iso-" + year`` and only rule files change it afterwards.

    ``raw`` is exported before any rule runs, so it carries exactly the seed. A clean-stage
    rule file then rewrites the seed for two polities, which covers the column name surviving
    the rule-file loader, validation and the engine, and its canonical slot in every export.
    """
    _assemble_input_tree(tmp_path)
    (tmp_path / "data" / "input" / "clean" / "clean_iso_whep.csv").write_text(
        "clean_column_source,clean_value_source_raw,clean_value_source,"
        "clean_column_target,clean_value_target_raw,clean_value_target\n"
        "polity,albania,albania,iso_whep,#REPLACE#,ALB\n"
        "polity,algeria,algeria,iso_whep,#REPLACE#,DZA\n",
        encoding="utf-8",
    )

    result = run_pipeline(
        root=tmp_path,
        options=RuntimeOptions(progress_enabled=False, ingest_parallel_workers=1),
    )

    def read(layer: str) -> pl.DataFrame:
        return pl.read_csv(
            result.processed_paths[f"whep_data_{layer}"], separator="\t", infer_schema_length=0
        )

    raw = read("raw")
    assert raw.select(
        (pl.col("iso_whep") == pl.concat_str(pl.lit("iso-"), pl.col("year"))).all()
    ).item(), "raw must carry exactly the ingest seed"

    for layer in ("raw", "clean", "normalize", "harmonize"):
        frame = read(layer)
        columns = frame.columns
        assert columns.index("continent") + 1 == columns.index("iso_whep") == (
            columns.index("polity") - 1
        ), f"{layer}: iso_whep is not between continent and polity"
        if layer == "raw":
            continue
        codes = frame.group_by("polity").agg(pl.col("iso_whep").unique())
        by_polity = dict(codes.iter_rows())
        assert by_polity["albania"] == ["ALB"], layer
        assert by_polity["algeria"] == ["DZA"], layer
        others = frame.filter(~pl.col("polity").is_in(["albania", "algeria"]))
        assert others["iso_whep"].str.starts_with("iso-").all(), f"{layer}: seed was rewritten"

    assert result.lists_paths["iso_whep"].name == "unique_iso_whep.xlsx"


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
    assert frame.columns == _EXPECTED_EXPORT_COLUMNS
    assert frame.height > 0
