r"""Postpro / diagnostics — standardize rule summaries.

* :func:`build_standardize_rule_catalog` — standardize-layer rules → the standardize audit
  catalog (meaningful rows only, deduplicated);
* :func:`summarize_standardize_rules` — normalize a standardize audit into the matched-rule
  summary (``affected_rows`` NA→0; numeric coercion; deterministic sort);
* :func:`build_unmatched_standardize_rule_summary` — the catalog rules that never matched, with a
  **normalized-key counts branch**: when matched-rule counts keyed by
  ``(rule_commodity_match_key, unit_source_key)`` are supplied, a catalog rule counts as matched
  when its normalized ``(commodity_key, unit_source)`` appears there (so a ``#ALL#`` rule
  applied to any commodity is matched); otherwise the matched-rule summary keys are used.

Null keys are folded to a sentinel before the anti-join so null matches null.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.postpro.diagnostics.rule_summaries import _anti_join_null_safe
from whep_digitize.setup.helpers.strings import normalize_string

# The whitespace class trimmed from values: space, tab, CR, LF.
_TRIM_CHARS = " \t\r\n"
_STD_CHAR_COLUMNS = (
    "rule_file_identifier",
    "commodity_key",
    "unit_source",
    "unit_target",
    "source_unit_raw",
)
_STD_NUM_COLUMNS = ("unit_factor", "unit_offset", "detected_prefix", "unit_factor_effective")
_STD_CATALOG_COLUMNS = (
    "rule_file_identifier",
    "commodity_key",
    "unit_source",
    "unit_target",
    "unit_factor",
    "unit_offset",
    "source_unit_raw",
    "detected_prefix",
    "unit_factor_effective",
)
_STD_SUMMARY_COLUMNS = ("affected_rows", *_STD_CATALOG_COLUMNS)
_STD_SORT = ("rule_file_identifier", "commodity_key", "unit_source", "unit_target")


def _std_dtype(column: str) -> type[pl.DataType]:
    if column == "affected_rows":
        return pl.Int64
    return pl.Float64 if column in _STD_NUM_COLUMNS else pl.String


_STD_CATALOG_SCHEMA: dict[str, type[pl.DataType]] = {c: _std_dtype(c) for c in _STD_CATALOG_COLUMNS}
_STD_SUMMARY_SCHEMA: dict[str, type[pl.DataType]] = {c: _std_dtype(c) for c in _STD_SUMMARY_COLUMNS}


def _blank_to_null(column: str) -> pl.Expr:
    """Cast to String and map a whitespace-only / empty value to null."""
    text = pl.col(column).cast(pl.String)
    return (
        pl.when(text.str.strip_chars(_TRIM_CHARS).str.len_chars() == 0)
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(text)
        .alias(column)
    )


def build_standardize_rule_catalog(layer_rules_df: pl.DataFrame) -> pl.DataFrame:
    """Convert standardize-layer rules to the standardize audit catalog (deduplicated).

    Args:
        layer_rules_df: The prepared standardize-layer rules.

    Returns:
        The 9-column catalog (meaningful rows only), or an empty typed frame.
    """
    if layer_rules_df.height == 0:
        return pl.DataFrame(schema=_STD_CATALOG_SCHEMA)

    rename = {"source_rule_file": "rule_file_identifier"}
    frame = layer_rules_df.rename({k: v for k, v in rename.items() if k in layer_rules_df.columns})
    additions = [
        pl.lit(None, dtype=_STD_CATALOG_SCHEMA[column]).alias(column)
        for column in _STD_CATALOG_COLUMNS
        if column not in frame.columns
    ]
    if additions:
        frame = frame.with_columns(additions)

    catalog = frame.select(
        *(
            pl.col(column).cast(_STD_CATALOG_SCHEMA[column]).alias(column)
            for column in _STD_CATALOG_COLUMNS
        )
    ).with_columns(_blank_to_null(column) for column in _STD_CHAR_COLUMNS)
    meaningful = (
        pl.col("commodity_key").is_not_null()
        | pl.col("unit_source").is_not_null()
        | pl.col("unit_target").is_not_null()
    )
    return catalog.filter(meaningful).unique(maintain_order=True)


def summarize_standardize_rules(audit_df: pl.DataFrame) -> pl.DataFrame:
    """Normalize a standardize audit into the canonical matched-rule summary.

    Args:
        audit_df: The standardize audit table.

    Returns:
        The 10-column summary, sorted deterministically (empty typed frame when audit is empty).
    """
    additions = [
        pl.lit(None, dtype=_STD_SUMMARY_SCHEMA[column]).alias(column)
        for column in _STD_SUMMARY_COLUMNS
        if column not in audit_df.columns
    ]
    frame = audit_df.with_columns(additions) if additions else audit_df
    frame = frame.with_columns(
        pl.col("affected_rows").cast(pl.Int64, strict=False).fill_null(0),
        *(pl.col(column).cast(pl.Float64, strict=False) for column in _STD_NUM_COLUMNS),
    ).with_columns(_blank_to_null(column) for column in _STD_CHAR_COLUMNS)

    if frame.height == 0:
        return pl.DataFrame(schema=_STD_SUMMARY_SCHEMA)
    return frame.sort(_STD_SORT, nulls_last=True, maintain_order=True).select(_STD_SUMMARY_COLUMNS)


def build_unmatched_standardize_rule_summary(
    rule_catalog_df: pl.DataFrame,
    matched_rule_summary_df: pl.DataFrame,
    matched_rule_counts_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Return the standardize rules that never matched, with ``affected_rows = 0``.

    the
    normalized-key counts branch.

    Args:
        rule_catalog_df: The standardize rule catalog.
        matched_rule_summary_df: The matched-rule summary.
        matched_rule_counts_df: Optional counts keyed by ``(rule_commodity_match_key,
            unit_source_key)``; when present (and keyed), a catalog rule is matched when its
            normalized ``(commodity_key, unit_source)`` appears there.

    Returns:
        The 10-column unmatched summary (empty typed frame when nothing is unmatched).
    """
    if rule_catalog_df.height == 0:
        return pl.DataFrame(schema=_STD_SUMMARY_SCHEMA)

    catalog = _coerce_std_keys(rule_catalog_df).with_columns(
        normalize_string(rule_catalog_df.get_column("commodity_key").cast(pl.String)).alias(
            "rule_commodity_match_key"
        ),
        normalize_string(rule_catalog_df.get_column("unit_source").cast(pl.String)).alias(
            "unit_source_key"
        ),
    )
    rule_key = catalog.select(_STD_CATALOG_COLUMNS).unique(maintain_order=True)

    counts = matched_rule_counts_df if matched_rule_counts_df is not None else pl.DataFrame()
    use_counts = counts.height > 0 and {"rule_commodity_match_key", "unit_source_key"} <= set(
        counts.columns
    )
    if use_counts:
        count_keys = counts.select(
            normalize_string(counts.get_column("rule_commodity_match_key").cast(pl.String)).alias(
                "rule_commodity_match_key"
            ),
            normalize_string(counts.get_column("unit_source_key").cast(pl.String)).alias(
                "unit_source_key"
            ),
        ).unique()
        matched_key = (
            catalog.join(
                count_keys, on=["rule_commodity_match_key", "unit_source_key"], how="inner"
            )
            .select(_STD_CATALOG_COLUMNS)
            .unique()
        )
    else:
        matched_key = (
            _coerce_std_keys(matched_rule_summary_df).select(_STD_CATALOG_COLUMNS).unique()
        )

    unmatched = _anti_join_null_safe(rule_key, matched_key, _STD_CATALOG_COLUMNS)
    if unmatched.height == 0:
        return pl.DataFrame(schema=_STD_SUMMARY_SCHEMA)

    return (
        unmatched.with_columns(pl.lit(0, dtype=pl.Int64).alias("affected_rows"))
        .sort(_STD_SORT, nulls_last=True, maintain_order=True)
        .select(_STD_SUMMARY_COLUMNS)
    )


def _coerce_std_keys(frame: pl.DataFrame) -> pl.DataFrame:
    """Add + coerce the standardize catalog key columns (char → String, numeric → Float64)."""
    additions = [
        pl.lit(None, dtype=_STD_CATALOG_SCHEMA[column]).alias(column)
        for column in _STD_CATALOG_COLUMNS
        if column not in frame.columns
    ]
    frame = frame.with_columns(additions) if additions else frame
    return frame.with_columns(
        *(pl.col(column).cast(pl.String) for column in _STD_CHAR_COLUMNS),
        *(pl.col(column).cast(pl.Float64, strict=False) for column in _STD_NUM_COLUMNS),
    )
