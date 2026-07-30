r"""Long-format validation — the Python port of ``13-validate.R``.

``validate_long_df_by_document`` runs the three long-format checks (mandatory-field,
year-value, duplicate) for every document in one pass and returns the validated data plus a
verbatim, deterministically-ordered error vector. A downstream consumer compares the error
*text*, so the message formats and their order are reproduced exactly:

* **Document-major frame.** Rows are regrouped so each document's rows are contiguous, in
  first-appearance document order, preserving within-document order (R ``order(chmatch(...))``).
  Per-document row ids (R ``rowidv``) and absolute row positions feed the message text and the
  sort keys.
* **4-key stable sort.** Every error carries ``(document_rank, type_rank, key_a, key_b)`` and
  the combined errors are sorted by that tuple (R ``setorder``): within a document, mandatory
  errors (by column then row), then year errors (by year first-appearance then check kind),
  then duplicate errors (by group first-appearance).

The R ``current_year`` comes from ``Sys.Date()``; it is exposed here as a parameter (defaulting
to the system year, matching R) so the plausible-year range is deterministic in tests — the
same rationale R gives for ``validate_year_values(current_year=)``.

R source: ``r/1-import_pipeline/13-output/13-validate.R`` (``validate_long_df_by_document``; the
non-vectorized ``validate_long_df`` + per-check helpers are the reference it replaces).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.assertions import require

_STAGE_ROW_ORDER = get_pipeline_constants().sorting.stage_row_order
_MIN_YEAR = 1900
_YEAR_RANGE_RE = re.compile(r"^\d{4}-\d{4}$")
_YEAR_PLAIN_RE = re.compile(r"^\d{4}$")

_TYPE_MANDATORY = 1
_TYPE_YEAR = 2
_TYPE_DUPLICATE = 3


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of long-format validation (R ``list(data, errors)``)."""

    data: pl.DataFrame
    errors: tuple[str, ...]


class _ErrorRecord(NamedTuple):
    """One error with its four sort keys (R error-table row)."""

    document_rank: int
    type_rank: int
    key_a: int
    key_b: int
    message: str


def _r_str(value: object) -> str:
    """Coerce a value for message embedding, mapping ``None`` -> ``"NA"`` (R ``as.character``)."""
    return "NA" if value is None else str(value)


_ERROR_FRAME_SCHEMA: dict[str, type[pl.DataType]] = {
    "document_rank": pl.Int64,
    "type_rank": pl.Int64,
    "key_a": pl.Int64,
    "key_b": pl.Int64,
    "message": pl.String,
}


def _mandatory_field_error_frame(work: pl.DataFrame, mandatory_cols: list[str]) -> pl.DataFrame:
    """Per document, column-major then row: rows with a null/blank mandatory value (vectorized).

    Built entirely in polars — the message via ``pl.format`` — rather than a per-row Python loop:
    on the real dataset these are the overwhelming majority of the error volume (150k+). The four
    sort keys and the message text match the R error-table rows exactly.
    """
    frames = [
        work.filter(pl.col(col).is_null() | (pl.col(col) == "")).select(
            pl.col("_document_rank").cast(pl.Int64).alias("document_rank"),
            pl.lit(_TYPE_MANDATORY, dtype=pl.Int64).alias("type_rank"),
            pl.lit(col_index, dtype=pl.Int64).alias("key_a"),
            pl.col("_global_row").cast(pl.Int64).alias("key_b"),
            pl.format(
                "missing mandatory value in document '{}', row_id '{}', column '{}'",
                pl.col("document").fill_null("NA"),
                pl.col("_row_id_in_doc"),
                pl.lit(col),
            ).alias("message"),
        )
        for col_index, col in enumerate(mandatory_cols, start=1)
    ]
    return pl.concat(frames) if frames else pl.DataFrame(schema=_ERROR_FRAME_SCHEMA)


def _records_to_frame(records: list[_ErrorRecord]) -> pl.DataFrame:
    """Materialize the low-volume year / duplicate check records as an error frame."""
    if not records:
        return pl.DataFrame(schema=_ERROR_FRAME_SCHEMA)
    return pl.DataFrame(
        {
            "document_rank": [record.document_rank for record in records],
            "type_rank": [record.type_rank for record in records],
            "key_a": [record.key_a for record in records],
            "key_b": [record.key_b for record in records],
            "message": [record.message for record in records],
        },
        schema=_ERROR_FRAME_SCHEMA,
    )


def _year_value_errors(work: pl.DataFrame, max_year: int) -> list[_ErrorRecord]:
    """Per document, first-appearance year order: implausible plain years and ranges."""
    year_pairs = (
        work.select("_document_rank", "year", "_global_row")
        .unique(subset=["_document_rank", "year"], keep="first", maintain_order=True)
        .filter(pl.col("year").is_not_null() & (pl.col("year") != ""))
    )
    records: list[_ErrorRecord] = []
    for row in year_pairs.iter_rows(named=True):
        year = row["year"]
        rank = row["_document_rank"]
        appearance = row["_global_row"]
        if _YEAR_RANGE_RE.match(year):
            start_text, end_text = year.split("-")
            start, end = int(start_text), int(end_text)
            if start > end:
                records.append(
                    _ErrorRecord(
                        rank,
                        _TYPE_YEAR,
                        appearance,
                        1,
                        f"year range '{year}' has start year greater than end year",
                    )
                )
            if start < _MIN_YEAR or end > max_year:
                records.append(
                    _ErrorRecord(
                        rank,
                        _TYPE_YEAR,
                        appearance,
                        2,
                        f"year range '{year}' contains year outside plausible range "
                        f"[{_MIN_YEAR}, {max_year}]",
                    )
                )
        elif _YEAR_PLAIN_RE.match(year):
            value = int(year)
            if value < _MIN_YEAR or value > max_year:
                records.append(
                    _ErrorRecord(
                        rank,
                        _TYPE_YEAR,
                        appearance,
                        1,
                        f"year value '{year}' is outside plausible range [{_MIN_YEAR}, {max_year}]",
                    )
                )
    return records


def _duplicate_errors(work: pl.DataFrame, doc_rank_map: dict[object, int]) -> list[_ErrorRecord]:
    """Groups (full identity key) repeated more than once, in group first-appearance order."""
    key_columns = [col for col in _STAGE_ROW_ORDER if col in work.columns]
    if not key_columns:
        return []
    duplicates = (
        work.group_by(key_columns, maintain_order=True)
        .agg(pl.len().alias("duplicate_count"))
        .filter(pl.col("duplicate_count") > 1)
    )
    records: list[_ErrorRecord] = []
    for group_index, row in enumerate(duplicates.iter_rows(named=True), start=1):
        key_description = ", ".join(f"{col} = {_r_str(row[col])}" for col in key_columns)
        message = (
            f"duplicate entries detected (count {row['duplicate_count']}) for {key_description}"
        )
        records.append(
            _ErrorRecord(doc_rank_map[row["document"]], _TYPE_DUPLICATE, group_index, 1, message)
        )
    return records


def validate_long_df_by_document(
    long_df: pl.DataFrame, config: Config, current_year: int | None = None
) -> ValidationResult:
    """Validate a long-format frame for every document in one pass.

    Args:
        long_df: Long-format frame with a ``document`` column.
        config: Pipeline configuration (``column_required`` are the mandatory columns).
        current_year: Reference year for the plausible-year range ``[1900, current_year + 1]``;
            defaults to the system year (R ``Sys.Date()``).

    Returns:
        A :class:`ValidationResult` with the document-major validated frame and the verbatim
        error messages, ordered by ``(document_rank, type_rank, key_a, key_b)``.

    Raises:
        ValidationError: If ``config.column_required`` is empty or ``long_df`` lacks the
            ``document`` (or, when non-empty, ``year``) column.
    """
    require(len(config.column_required) >= 1, "config.column_required must be non-empty")
    require("document" in long_df.columns, "long_df must have a 'document' column")

    mandatory_cols = list(config.column_required)
    work = long_df
    missing_cols = [col for col in mandatory_cols if col not in work.columns]
    if missing_cols:
        work = work.with_columns([pl.lit(None, dtype=pl.String).alias(col) for col in missing_cols])

    data_columns = work.columns
    if work.height == 0:
        return ValidationResult(data=work, errors=())

    require("year" in work.columns, "long_df must have a 'year' column")
    resolved_year = current_year if current_year is not None else date.today().year
    max_year = resolved_year + 1

    # Document-major: order documents by first appearance, keep within-document order; then
    # per-document row id, and the absolute row position (both feed messages + sort keys).
    work = (
        work.with_row_index("_orig")
        .with_columns(pl.col("_orig").min().over("document").alias("_doc_first"))
        .sort(["_doc_first", "_orig"], maintain_order=True)
        .with_columns(
            (pl.col("_doc_first").rle_id() + 1).alias("_document_rank"),
            (pl.int_range(pl.len()).over("document") + 1).alias("_row_id_in_doc"),
            (pl.int_range(pl.len()) + 1).alias("_global_row"),
        )
    )
    doc_rank_map: dict[object, int] = dict(
        work.select("document", "_document_rank").unique().iter_rows()
    )

    # Assemble every check's errors as one frame and sort by the 4 keys in polars (R setorder).
    # The keys are unique within each check (mandatory: global row + column; year: appearance +
    # kind; duplicate: group index), so the ordering is fully key-determined — byte-identical to
    # the previous stable Python sort. ``maintain_order`` keeps it deterministic regardless.
    error_frame = pl.concat(
        [
            _mandatory_field_error_frame(work, mandatory_cols),
            _records_to_frame(_year_value_errors(work, max_year)),
            _records_to_frame(_duplicate_errors(work, doc_rank_map)),
        ]
    ).sort(["document_rank", "type_rank", "key_a", "key_b"], maintain_order=True)
    errors = tuple(error_frame.get_column("message").to_list())

    return ValidationResult(data=work.select(data_columns), errors=errors)
