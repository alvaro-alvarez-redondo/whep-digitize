"""Postpro / utilities — rule-template workbooks and rule-file loading.

* :func:`read_rule_table` — read a rule file (``.csv`` / ``.xlsx`` / ``.xls``) **all-as-text**
  (rules match character data, so ``"007"`` / ``"1000.0"`` must keep their exact source string).
  For workbooks, every sheet whose columns — after stripping a ``clean_`` / ``harmonize_``
  prefix — match the canonical rule schema (no duplicates, no unexpected columns, all required
  present) is kept and row-bound in workbook order; a file with no matching sheet aborts.
* :func:`write_stage_rule_template` / :func:`generate_postpro_rule_templates` — write the unified
  clean/harmonize rule template (canonical columns + a guidance sheet).
* :func:`load_stage_rule_payloads` — discover the stage's ``clean_*`` / ``harmonize_*`` rule
  files (deterministically ordered) and read each into a :class:`RulePayload`.

Excel reads use ``fastexcel`` + ``pl.read_excel(engine="calamine", infer_schema_length=0)`` so
that no column is ever type-inferred; writes use ``openpyxl``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fastexcel
import polars as pl
from openpyxl import Workbook

from whep_digitize.postpro.utilities.output_roots import initialize_postpro_output_root
from whep_digitize.postpro.utilities.stage_definitions import (
    get_canonical_rule_columns,
    validate_postpro_stage_name,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import ensure_directories_exist
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.strings import (
    canonicalize_token_cell,
    resolve_exact_match_directive,
)

_CONSTANTS = get_pipeline_constants()
_EXACT_TOKEN = _CONSTANTS.postpro.rule_match_exact_token
_TEMPLATE_FILE_NAME = _CONSTANTS.postpro.clean_harmonize_template_file_name
_OPTIONAL_RULE_COLUMN = _CONSTANTS.postpro.stage_source_value_column
_STAGE_PREFIX_RE = re.compile(r"^(clean|harmonize)_")
_RULE_EXTENSION_RE = re.compile(r"\.(xlsx|xls|csv)$")
# Rule CSVs treat an empty cell and the literal string "NA" alike: both mean "no value". polars
# keeps "NA" as a plain string by default, so both tokens are declared explicitly — an unset
# target/value cell must read back as null, never as the two-character string "NA".
_CSV_NA_VALUES = ("", "NA")
_GUIDANCE_NOTES = (
    "Fill all required columns.",
    "Column names must remain unchanged.",
    "Rows define conditional source-target replacements.",
)
_STAGE_IMPORT_DIR_ATTR = {"clean": "cleaning", "harmonize": "harmonization"}


@dataclass(frozen=True, slots=True)
class RulePayload:
    """One discovered rule file and its raw contents.

    Attributes:
        rule_file_id: The rule file's base name.
        rule_file_path: The rule file's absolute forward-slash path.
        raw_rules: The rule rows read all-as-text (pre-canonicalization).
    """

    rule_file_id: str
    rule_file_path: str
    raw_rules: pl.DataFrame


def read_rule_table(file_path: Path | str) -> pl.DataFrame:
    """Read a rule file all-as-text into a frame.

    Every column stays a ``String``: rules match character data, so a cell must keep its exact
    source text. For ``.csv`` files both empty cells and the literal ``"NA"`` become null.

    Args:
        file_path: Path to a ``.csv`` / ``.xlsx`` / ``.xls`` rule file.

    Returns:
        The rule rows as an all-``String`` frame (workbook sheets row-bound in order).

    Raises:
        ValidationError: If the path is blank/missing, the extension is unsupported, or no
            workbook sheet matches the canonical rule schema.
    """
    path = Path(file_path)
    require(len(str(path)) >= 1, "file_path must be a non-empty path")
    require(path.is_file(), f"rule file does not exist: {path}")

    extension = path.suffix.lower().lstrip(".")
    if extension == "csv":
        frame = pl.read_csv(path, infer_schema_length=0, null_values=list(_CSV_NA_VALUES))
    elif extension in ("xlsx", "xls"):
        frame = _read_rule_workbook(path)
    else:
        raise ValidationError(f"Unsupported rule extension for {path}")
    return canonicalize_rule_token_cells(frame)


def canonicalize_rule_token_cells(rules: pl.DataFrame) -> pl.DataFrame:
    """Canonicalize every ``;``-delimited rule cell: split, trim, dedupe, sort, rejoin.

    Applied to every string column as the rule file is loaded, so authoring order and incidental
    duplicates never reach the engine: ``"c; a; b; a"`` becomes ``"a; b; c"``. Canonicalization is
    strictly **within one cell** — tokens are never mixed, shared, or reordered across cells, rows,
    or columns.

    An ``#EXACT#`` prefix is split off first and re-attached afterwards. Sorting the marker along
    with the tokens could move it away from the start of the cell (``"#EXACT#c; a"`` ->
    ``"a; #EXACT#c"``), which would stop it being recognised as the directive.

    Args:
        rules: The freshly-read rule frame (not mutated).

    Returns:
        A new frame with every string column canonicalized.
    """
    string_columns = [
        name for name, dtype in zip(rules.columns, rules.dtypes, strict=True) if dtype == pl.String
    ]
    if not string_columns:
        return rules

    def canonicalize(value: str | None) -> str | None:
        body, is_exact = resolve_exact_match_directive(value)
        canonical = canonicalize_token_cell(body)
        if not is_exact:
            return canonical
        return f"{_EXACT_TOKEN}{canonical}" if canonical is not None else _EXACT_TOKEN

    return rules.with_columns(
        [
            rules.get_column(name).map_elements(canonicalize, return_dtype=pl.String).alias(name)
            for name in string_columns
        ]
    )


def _read_rule_workbook(path: Path) -> pl.DataFrame:
    """Read and row-bind every canonical-schema-matching worksheet of a rule workbook."""
    canonical_columns = get_canonical_rule_columns()
    required_columns = tuple(
        column for column in canonical_columns if column != _OPTIONAL_RULE_COLUMN
    )
    sheet_names = list(fastexcel.read_excel(str(path)).sheet_names)

    matching_frames: list[pl.DataFrame] = []
    for sheet_name in sheet_names:
        sheet = pl.read_excel(path, sheet_name=sheet_name, engine="calamine", infer_schema_length=0)
        available = sheet.columns
        normalized = [_STAGE_PREFIX_RE.sub("", column) for column in available]
        has_duplicate = len(set(normalized)) != len(normalized)
        has_unexpected = any(column not in canonical_columns for column in normalized)
        has_required = all(column in normalized for column in required_columns)
        if has_duplicate or has_unexpected or not has_required:
            continue
        renames = {old: new for old, new in zip(available, normalized, strict=True) if old != new}
        matching_frames.append(sheet.rename(renames) if renames else sheet)

    if not matching_frames:
        raise ValidationError(
            f"No worksheets with matching rule columns found in {path}. "
            f"Required columns: {', '.join(required_columns)}. "
            f"Available sheets: {', '.join(sheet_names)}"
        )
    return pl.concat(matching_frames, how="diagonal")


def write_stage_rule_template(templates_dir: Path, overwrite: bool = True) -> Path:
    """Write the unified clean/harmonize rule template workbook.

    The workbook holds a ``clean_harmonize_template`` sheet with the canonical rule columns
    (header row only) plus a ``guidance`` sheet of editing notes.

    Args:
        templates_dir: The directory to write the template into.
        overwrite: When ``False`` and the template already exists, it is left untouched.

    Returns:
        The template file path.

    Raises:
        ValidationError: If ``templates_dir`` is blank.
    """
    require(len(str(templates_dir)) >= 1, "templates_dir must be a non-empty path")
    template_path = templates_dir / _TEMPLATE_FILE_NAME
    if template_path.exists() and not overwrite:
        return template_path

    workbook = Workbook()
    template_sheet = workbook.active
    template_sheet.title = "clean_harmonize_template"
    template_sheet.append(list(get_canonical_rule_columns()))

    guidance_sheet = workbook.create_sheet("guidance")
    guidance_sheet.append(["note"])
    for note in _GUIDANCE_NOTES:
        guidance_sheet.append([note])

    ensure_directories_exist([templates_dir])
    workbook.save(template_path)
    return template_path


def generate_postpro_rule_templates(config: Config, overwrite: bool = True) -> Path:
    """Create the post-processing output root and write the rule template.

    Args:
        config: The resolved pipeline configuration.
        overwrite: Whether to overwrite an existing template.

    Returns:
        The written template path.
    """
    paths = initialize_postpro_output_root(config)
    return write_stage_rule_template(paths.templates_dir, overwrite=overwrite)


def discover_stage_rule_files(config: Config, stage_name: str) -> list[Path]:
    """Discover a stage's rule files, deterministically ordered by file name (C-locale).

    Shared by :func:`load_stage_rule_payloads` and the runtime-cache key builder. The stage
    import directory is created if absent, so a first run on a fresh checkout does not fail.

    Args:
        config: The resolved pipeline configuration.
        stage_name: The execution stage (``clean`` or ``harmonize``).

    Returns:
        The ordered ``clean_*`` / ``harmonize_*`` rule file paths (``.xlsx`` / ``.xls`` / ``.csv``).
    """
    stage = validate_postpro_stage_name(stage_name)
    import_dir = getattr(config.paths.data.import_, _STAGE_IMPORT_DIR_ATTR[stage])
    ensure_directories_exist([import_dir])

    stage_prefix = f"{stage}_"
    return sorted(
        (
            entry
            for entry in import_dir.iterdir()
            if entry.is_file()
            and _RULE_EXTENSION_RE.search(entry.name)
            and entry.name.startswith(stage_prefix)
        ),
        key=lambda entry: entry.name,
    )


def load_stage_rule_payloads(config: Config, stage_name: str) -> list[RulePayload]:
    """Discover a stage's rule files (deterministically ordered) and read each all-as-text.

    Args:
        config: The resolved pipeline configuration.
        stage_name: The execution stage (``clean`` or ``harmonize``).

    Returns:
        One :class:`RulePayload` per matching rule file, ordered by file name (C-locale).
    """
    return [
        RulePayload(
            rule_file_id=entry.name,
            rule_file_path=entry.resolve().as_posix(),
            raw_rules=read_rule_table(entry),
        )
        for entry in discover_stage_rule_files(config, stage_name)
    ]
