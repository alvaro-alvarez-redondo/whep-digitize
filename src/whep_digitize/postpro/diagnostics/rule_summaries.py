r"""Postpro / diagnostics — clean/harmonize rule summaries.

* :func:`summarize_stage_rules` — normalize a clean/harmonize stage audit into a canonical,
  row-per-record matched-rule summary (``value_source``/``value_target`` filled from the
  ``*_result`` columns; ``affected_rows`` NA→0; deterministic sort);
* :func:`build_stage_rule_catalog_from_payloads` — flatten the rule payloads into the canonical
  rule catalog (meaningful rows only, deduplicated);
* :func:`build_unmatched_rule_summary` — the catalog rows that never matched (an anti-join on the
  rule key), emitted with ``affected_rows = 0``.

Null-key note: polars joins do not match null to null, so
the anti-join folds null keys to a sentinel first (:func:`_anti_join_null_safe`).
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from whep_digitize.postpro.utilities.templates import RulePayload

# The whitespace class trimmed from values: space, tab, CR, LF.
_TRIM_CHARS = " \t\r\n"
# Sentinel that folds null keys so null matches null under polars joins.
_NA_SENTINEL = "\x00__whep_diag_na__"

_STAGE_SUMMARY_COLUMNS = (
    "loop",
    "affected_rows",
    "rule_file_identifier",
    "column_source",
    "value_source_raw",
    "value_source",
    "column_target",
    "value_target_raw",
    "value_target",
)
_STAGE_SUMMARY_SCHEMA: dict[str, type[pl.DataType]] = {
    column: (pl.Int64 if column in ("loop", "affected_rows") else pl.String)
    for column in _STAGE_SUMMARY_COLUMNS
}
_STAGE_SORT = (
    "loop",
    "rule_file_identifier",
    "column_source",
    "column_target",
    "value_source_raw",
    "value_target_raw",
)
_CATALOG_COLUMNS = (
    "rule_file_identifier",
    "column_source",
    "value_source_raw",
    "value_source",
    "column_target",
    "value_target_raw",
    "value_target",
)
_UNMATCHED_KEY = (
    "rule_file_identifier",
    "column_source",
    "value_source_raw",
    "column_target",
    "value_target_raw",
)


def _anti_join_null_safe(
    left: pl.DataFrame, right_keys: pl.DataFrame, keys: Sequence[str]
) -> pl.DataFrame:
    """Anti-join ``left`` against ``right_keys``, treating null as equal to null."""
    fold_names = [f"__key_{index}__" for index in range(len(keys))]
    folded_left = left.with_columns(
        pl.col(key).cast(pl.String).fill_null(_NA_SENTINEL).alias(fold)
        for key, fold in zip(keys, fold_names, strict=True)
    )
    folded_right = right_keys.select(
        pl.col(key).cast(pl.String).fill_null(_NA_SENTINEL).alias(fold)
        for key, fold in zip(keys, fold_names, strict=True)
    ).unique()
    return folded_left.join(folded_right, on=fold_names, how="anti").drop(fold_names)


def summarize_stage_rules(audit_df: pl.DataFrame) -> pl.DataFrame:
    """Normalize a clean/harmonize stage audit into the canonical matched-rule summary.

    Args:
        audit_df: The stage audit table.

    Returns:
        The 9-column summary, sorted deterministically (empty typed frame when the audit is empty).
    """
    frame = audit_df
    if "value_source" not in frame.columns and "value_source_result" in frame.columns:
        frame = frame.with_columns(pl.col("value_source_result").alias("value_source"))
    if "value_target" not in frame.columns and "value_target_result" in frame.columns:
        frame = frame.with_columns(pl.col("value_target_result").alias("value_target"))

    additions = [
        pl.lit(None, dtype=_STAGE_SUMMARY_SCHEMA[column]).alias(column)
        for column in _STAGE_SUMMARY_COLUMNS
        if column not in frame.columns
    ]
    if additions:
        frame = frame.with_columns(additions)

    frame = frame.with_columns(
        pl.col("loop").cast(pl.Int64, strict=False),
        pl.col("affected_rows").cast(pl.Int64, strict=False).fill_null(0),
    )
    if frame.height == 0:
        return pl.DataFrame(schema=_STAGE_SUMMARY_SCHEMA)
    return frame.sort(_STAGE_SORT, nulls_last=True, maintain_order=True).select(
        _STAGE_SUMMARY_COLUMNS
    )


def build_stage_rule_catalog_from_payloads(rule_payloads: Sequence[RulePayload]) -> pl.DataFrame:
    """Flatten rule payloads into the canonical, deduplicated rule catalog.

    Args:
        rule_payloads: The stage's rule payloads (from ``load_stage_rule_payloads``).

    Returns:
        The 7-column catalog (meaningful rows only), or an empty typed frame.
    """
    empty = pl.DataFrame(schema=dict.fromkeys(_CATALOG_COLUMNS, pl.String))
    frames: list[pl.DataFrame] = []
    for payload in rule_payloads:
        raw = payload.raw_rules
        if raw.height == 0:
            continue
        frames.append(_catalog_frame(raw, payload.rule_file_id))

    if not frames:
        return empty
    combined = pl.concat(frames, how="diagonal")
    if combined.height == 0:
        return empty
    return combined.unique(maintain_order=True)


def build_unmatched_rule_summary(
    rule_catalog_df: pl.DataFrame, matched_rule_summary_df: pl.DataFrame
) -> pl.DataFrame:
    """Return the catalog rules that never matched (anti-join), with ``affected_rows = 0``.

    Args:
        rule_catalog_df: The canonical rule catalog.
        matched_rule_summary_df: The matched-rule summary (from :func:`summarize_stage_rules`).

    Returns:
        The 9-column unmatched summary (empty typed frame when nothing is unmatched).
    """
    if rule_catalog_df.height == 0:
        return pl.DataFrame(schema=_STAGE_SUMMARY_SCHEMA)

    catalog = _ensure_columns(rule_catalog_df, _CATALOG_COLUMNS)
    rule_key = catalog.select(_CATALOG_COLUMNS).unique(maintain_order=True)
    matched_key = _ensure_columns(matched_rule_summary_df, _UNMATCHED_KEY).select(_UNMATCHED_KEY)

    unmatched = _anti_join_null_safe(rule_key, matched_key, _UNMATCHED_KEY)
    if unmatched.height == 0:
        return pl.DataFrame(schema=_STAGE_SUMMARY_SCHEMA)

    return (
        unmatched.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("loop"),
            pl.lit(0, dtype=pl.Int64).alias("affected_rows"),
        )
        .sort(
            [
                "rule_file_identifier",
                "column_source",
                "column_target",
                "value_source_raw",
                "value_target_raw",
            ],
            nulls_last=True,
            maintain_order=True,
        )
        .select(_STAGE_SUMMARY_COLUMNS)
    )


def _ensure_columns(frame: pl.DataFrame, columns: Sequence[str]) -> pl.DataFrame:
    """Add any missing columns as null ``String`` and cast the named columns to ``String``."""
    additions = [
        pl.lit(None, dtype=pl.String).alias(column)
        for column in columns
        if column not in frame.columns
    ]
    frame = frame.with_columns(additions) if additions else frame
    return frame.with_columns(pl.col(column).cast(pl.String) for column in columns)


def _blank_to_null(column: str) -> pl.Expr:
    """Cast to String and map a whitespace-only / empty value to null."""
    text = pl.col(column).cast(pl.String)
    return (
        pl.when(text.str.strip_chars(_TRIM_CHARS).str.len_chars() == 0)
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(text)
        .alias(column)
    )


def _catalog_frame(raw: pl.DataFrame, rule_file_id: str) -> pl.DataFrame:
    """Coerce one payload's raw rules into the canonical catalog schema + meaningful-row filter."""
    frame = raw
    if "column_source" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias("column_source"))
    if "column_target" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias("column_target"))
    if "value_source_raw" not in frame.columns:
        source = (
            pl.col("value_source")
            if "value_source" in frame.columns
            else pl.lit(None, dtype=pl.String)
        )
        frame = frame.with_columns(source.cast(pl.String).alias("value_source_raw"))
    if "value_target_raw" not in frame.columns:
        target = (
            pl.col("value_target")
            if "value_target" in frame.columns
            else pl.lit(None, dtype=pl.String)
        )
        frame = frame.with_columns(target.cast(pl.String).alias("value_target_raw"))
    if "value_source" not in frame.columns:
        frame = frame.with_columns(pl.col("value_source_raw").cast(pl.String).alias("value_source"))
    if "value_target" not in frame.columns:
        frame = frame.with_columns(pl.col("value_target_raw").cast(pl.String).alias("value_target"))

    frame = frame.with_columns(pl.lit(rule_file_id, dtype=pl.String).alias("rule_file_identifier"))
    frame = frame.select(_CATALOG_COLUMNS).with_columns(
        _blank_to_null(column) for column in _CATALOG_COLUMNS
    )
    meaningful = (
        pl.col("column_source").is_not_null()
        | pl.col("value_source_raw").is_not_null()
        | pl.col("column_target").is_not_null()
        | pl.col("value_target_raw").is_not_null()
    )
    return frame.filter(meaningful)
