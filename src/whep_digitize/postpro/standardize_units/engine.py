r"""Postpro / standardize_units — the affine unit-conversion engine.

The Python port of ``r/2-postpro_pipeline/24-standardize_units/24-standardize-engine.R``
(``apply_standardize_rules``), the HIGH-risk numeric core (parity risk #9). For each row it:

1. coerces ``value`` to numeric (aborting on a non-blank non-numeric value);
2. **folds a leading numeric multiplier** in the unit string (``"1000 head"``, value 5 → 5000,
   unit ``"head"``; comma thousands stripped), applied only for a finite prefix ≠ 1;
3. **revert-probes**: a folded row reverts to its original prefixed unit only when a rule actually
   matches that original form (specific commodity, else ``"all commodity"``) — otherwise its
   decomposed base unit is kept so a base/fallback rule can apply;
4. **two-stage matches** the (commodity, unit) keys: specific commodity first, then the
   ``"all commodity"`` fallback;
5. **affine converts** matched rows (``value * factor + offset``) and rewrites the unit to the
   target.

Order is exactly fold → revert-probe → match → convert. R mutated ``mapped_df`` by reference and
returned a list; this port is functional and returns :class:`StandardizeResult`.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.numeric import coerce_numeric_series
from whep_digitize.setup.helpers.strings import normalize_string

_CONSTANTS = get_pipeline_constants()
_ALL_COMMODITY = _CONSTANTS.postpro.standardization.all_commodity_key
_MULTIPLIER_PATTERN = _CONSTANTS.patterns.standardize_multiplier_prefix


@dataclass(frozen=True, slots=True)
class StandardizeResult:
    """Result of :func:`apply_standardize_rules` (R ``list(data, ...)``).

    Attributes:
        data: The dataset with ``value`` coerced/converted (Float64) and ``unit`` rewritten to the
            target (row order and other columns preserved).
        matched_count: Number of rows a rule converted.
        unmatched_count: Number of rows with a non-empty unit key that no rule matched.
        matched_rule_counts: Per-applied-rule affected-row counts + effective multiplier (empty
            frame with a 4-column schema when nothing matched).
    """

    data: pl.DataFrame
    matched_count: int
    unmatched_count: int
    matched_rule_counts: pl.DataFrame


def apply_standardize_rules(
    mapped_df: pl.DataFrame,
    prepared_rules_df: pl.DataFrame,
    unit_column: str,
    value_column: str,
    commodity_column: str,
) -> StandardizeResult:
    """Apply unit-standardization rules with multiplier fold, two-stage match, and affine convert.

    The Python port of R ``apply_standardize_rules``.

    Args:
        mapped_df: The dataset to standardize.
        prepared_rules_df: Prepared conversion rules (see
            :func:`~whep_digitize.postpro.standardize_units.rules_setup.prepare_standardize_rules`).
        unit_column: The unit column name.
        value_column: The numeric value column name.
        commodity_column: The commodity column name.

    Returns:
        A :class:`StandardizeResult`.

    Raises:
        ValidationError: If a required column is missing, or the value column contains a non-blank,
            non-numeric value.
    """
    for column, label in (
        (unit_column, "unit"),
        (value_column, "value"),
        (commodity_column, "commodity"),
    ):
        require(len(column) >= 1, f"{label} column name must be non-empty")
        if column not in mapped_df.columns:
            raise ValidationError(f"{label} column '{column}' is missing")

    raw_value = mapped_df.get_column(value_column)
    numeric_raw = coerce_numeric_series(raw_value)
    _abort_on_non_numeric(raw_value, numeric_raw)

    raw_unit = mapped_df.get_column(unit_column).cast(pl.String)
    original_key = normalize_string(raw_unit)
    commodity_key = normalize_string(mapped_df.get_column(commodity_column).cast(pl.String))

    working = _fold_multiplier(mapped_df.height, numeric_raw, raw_unit, original_key, commodity_key)
    has_rules = prepared_rules_df.height > 0
    if has_rules:
        working = _revert_prefixes(working, prepared_rules_df)

    if not has_rules:
        data = mapped_df.with_columns(
            working.get_column("numeric").alias(value_column),
            working.get_column("unit_str").alias(unit_column),
        )
        return StandardizeResult(
            data=data,
            matched_count=0,
            unmatched_count=_unit_nonempty_count(working.get_column("unit_key")),
            matched_rule_counts=_empty_matched_rule_counts(),
        )

    matched = _match_and_convert(working, prepared_rules_df)
    data = mapped_df.with_columns(
        matched.get_column("numeric").alias(value_column),
        matched.get_column("unit_str").alias(unit_column),
    )
    return StandardizeResult(
        data=data,
        matched_count=int(matched.get_column("is_matched").sum()),
        unmatched_count=int(
            (
                ~matched.get_column("is_matched")
                & matched.get_column("unit_key").is_not_null()
                & (matched.get_column("unit_key") != "")
            ).sum()
        ),
        matched_rule_counts=_build_matched_rule_counts(matched),
    )


def _abort_on_non_numeric(raw_value: pl.Series, numeric_raw: pl.Series) -> None:
    """Abort when a value is non-null, non-blank, yet fails numeric coercion (R invalid check)."""
    if raw_value.dtype == pl.String:
        blank = raw_value.is_not_null() & (raw_value.str.strip_chars() == "")
    else:
        blank = pl.Series([False] * raw_value.len(), dtype=pl.Boolean)
    invalid = raw_value.is_not_null() & ~blank & numeric_raw.is_null()
    if bool(invalid.any()):
        bad = raw_value.cast(pl.String).filter(invalid).unique().to_list()
        raise ValidationError(
            "value column contains non-numeric values that cannot be standardized: "
            f"{', '.join(str(value) for value in bad)}"
        )


def _fold_multiplier(
    height: int,
    numeric_raw: pl.Series,
    raw_unit: pl.Series,
    original_key: pl.Series,
    commodity_key: pl.Series,
) -> pl.DataFrame:
    """Fold a leading numeric multiplier in the unit string into the value (parity risk #9)."""
    working = pl.DataFrame(
        {
            "row_index": pl.Series("row_index", range(height), dtype=pl.UInt32),
            "numeric": numeric_raw,
            "numeric_raw": numeric_raw,
            "raw_unit": raw_unit,
            "original_key": original_key,
            "unit_key": original_key,
            "commodity_key": commodity_key,
            "detected_prefix": pl.Series("detected_prefix", [1.0] * height, dtype=pl.Float64),
            "unit_str": raw_unit,
        }
    ).with_columns(
        pl.col("raw_unit").str.extract(_MULTIPLIER_PATTERN, 1).alias("num_str"),
        pl.col("raw_unit").str.extract(_MULTIPLIER_PATTERN, 2).alias("base"),
    )
    working = working.with_columns(
        pl.col("num_str")
        .str.replace_all(",", "", literal=True)
        .str.strip_chars()
        .cast(pl.Float64, strict=False)
        .alias("fold_num")
    )
    working = working.with_columns(
        (
            pl.col("num_str").is_not_null()
            & (pl.col("num_str").str.len_chars() > 0)
            & pl.col("fold_num").is_not_null()
            & pl.col("fold_num").is_finite()
            & (pl.col("fold_num") != 1.0)
        ).alias("apply_fold")
    )
    working = working.with_columns(normalize_string(working.get_column("base")).alias("base_key"))
    fold = pl.col("apply_fold")
    return working.with_columns(
        pl.when(fold)
        .then(pl.col("numeric") * pl.col("fold_num"))
        .otherwise(pl.col("numeric"))
        .alias("numeric"),
        pl.when(fold)
        .then(pl.col("fold_num"))
        .otherwise(pl.col("detected_prefix"))
        .alias("detected_prefix"),
        pl.when(fold).then(pl.col("base_key")).otherwise(pl.col("unit_key")).alias("unit_key"),
        pl.when(fold)
        .then(pl.col("base").str.strip_chars())
        .otherwise(pl.col("unit_str"))
        .alias("unit_str"),
    )


def _revert_prefixes(working: pl.DataFrame, rules: pl.DataFrame) -> pl.DataFrame:
    """Revert a folded row to its original prefixed unit when a rule matches that original form."""
    folded = working.filter(pl.col("apply_fold"))
    if folded.height == 0:
        return working

    specific = folded.select("row_index", "commodity_key", "original_key").join(
        rules.select(
            pl.col("commodity_match_key"),
            pl.col("unit_source_key"),
            pl.col("unit_target").alias("revert_target"),
        ),
        left_on=["commodity_key", "original_key"],
        right_on=["commodity_match_key", "unit_source_key"],
        how="left",
    )
    fallback_rules = rules.filter(pl.col("commodity_match_key") == _ALL_COMMODITY)
    fallback = folded.select("row_index", "original_key").join(
        fallback_rules.select(
            pl.col("unit_source_key"), pl.col("unit_target").alias("revert_target")
        ),
        left_on="original_key",
        right_on="unit_source_key",
        how="left",
    )
    revert_ids = set(
        specific.filter(pl.col("revert_target").is_not_null()).get_column("row_index").to_list()
    ) | set(
        fallback.filter(pl.col("revert_target").is_not_null()).get_column("row_index").to_list()
    )
    if not revert_ids:
        return working

    revert = pl.col("row_index").is_in(list(revert_ids))
    return working.with_columns(
        pl.when(revert)
        .then(pl.col("original_key"))
        .otherwise(pl.col("unit_key"))
        .alias("unit_key"),
        pl.when(revert).then(pl.col("numeric_raw")).otherwise(pl.col("numeric")).alias("numeric"),
        pl.when(revert)
        .then(pl.lit(1.0))
        .otherwise(pl.col("detected_prefix"))
        .alias("detected_prefix"),
        pl.when(revert).then(pl.col("raw_unit")).otherwise(pl.col("unit_str")).alias("unit_str"),
    )


def _match_and_convert(working: pl.DataFrame, rules: pl.DataFrame) -> pl.DataFrame:
    """Two-stage match (specific → all-commodity) then affine convert the matched rows."""
    specific = working.join(
        rules.select(
            pl.col("commodity_match_key"),
            pl.col("unit_source_key"),
            pl.col("unit_target").alias("spec_target"),
            pl.col("unit_factor_num").alias("spec_factor"),
            pl.col("unit_offset_num").alias("spec_offset"),
        ),
        left_on=["commodity_key", "unit_key"],
        right_on=["commodity_match_key", "unit_source_key"],
        how="left",
    )
    fallback_rules = rules.filter(pl.col("commodity_match_key") == _ALL_COMMODITY).select(
        pl.col("unit_source_key"),
        pl.col("unit_target").alias("fb_target"),
        pl.col("unit_factor_num").alias("fb_factor"),
        pl.col("unit_offset_num").alias("fb_offset"),
    )
    joined = specific.join(
        fallback_rules, left_on="unit_key", right_on="unit_source_key", how="left"
    ).sort("row_index")

    spec_matched = pl.col("spec_target").is_not_null()
    unit_nonempty = pl.col("unit_key").is_not_null() & (pl.col("unit_key") != "")
    fb_matched = ~spec_matched & unit_nonempty & pl.col("fb_target").is_not_null()
    joined = joined.with_columns(
        spec_matched.alias("spec_matched"),
        fb_matched.alias("fb_matched"),
        (spec_matched | fb_matched).alias("is_matched"),
    )
    joined = joined.with_columns(
        pl.when(pl.col("spec_matched"))
        .then(pl.col("spec_target"))
        .when(pl.col("fb_matched"))
        .then(pl.col("fb_target"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("final_target"),
        pl.when(pl.col("spec_matched"))
        .then(pl.col("spec_factor"))
        .when(pl.col("fb_matched"))
        .then(pl.col("fb_factor"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("final_factor"),
        pl.when(pl.col("spec_matched"))
        .then(pl.col("spec_offset"))
        .when(pl.col("fb_matched"))
        .then(pl.col("fb_offset"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("final_offset"),
        pl.when(pl.col("spec_matched"))
        .then(pl.col("commodity_key"))
        .when(pl.col("fb_matched"))
        .then(pl.lit(_ALL_COMMODITY))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("rule_commodity_key"),
    )
    return joined.with_columns(
        pl.when(pl.col("is_matched"))
        .then(pl.col("numeric") * pl.col("final_factor") + pl.col("final_offset"))
        .otherwise(pl.col("numeric"))
        .alias("numeric"),
        pl.when(pl.col("is_matched"))
        .then(pl.col("final_target"))
        .otherwise(pl.col("unit_str"))
        .alias("unit_str"),
    )


def _build_matched_rule_counts(matched: pl.DataFrame) -> pl.DataFrame:
    """Group matched rows into per-applied-rule counts + the effective multiplier (R aggregate)."""
    rows = matched.filter(pl.col("is_matched"))
    if rows.height == 0:
        return _empty_matched_rule_counts()
    group_keys = [
        "rule_commodity_key",
        "commodity_key",
        "unit_key",
        "raw_unit",
        "final_factor",
        "detected_prefix",
    ]
    return (
        rows.group_by(group_keys, maintain_order=True)
        .agg(pl.len().cast(pl.Int64).alias("affected_rows"))
        .with_columns(
            (pl.col("final_factor") * pl.col("detected_prefix")).alias("unit_factor_effective")
        )
        .rename(
            {
                "rule_commodity_key": "rule_commodity_match_key",
                "commodity_key": "applied_commodity_match_key",
                "unit_key": "unit_source_key",
                "raw_unit": "source_unit_raw",
                "final_factor": "rule_multiplier",
            }
        )
        .select(
            "rule_commodity_match_key",
            "applied_commodity_match_key",
            "unit_source_key",
            "source_unit_raw",
            "rule_multiplier",
            "detected_prefix",
            "affected_rows",
            "unit_factor_effective",
        )
    )


def _empty_matched_rule_counts() -> pl.DataFrame:
    """Return the 4-column empty matched-rule-counts frame (R's zero-match / zero-rule schema)."""
    return pl.DataFrame(
        schema={
            "rule_commodity_match_key": pl.String,
            "applied_commodity_match_key": pl.String,
            "unit_source_key": pl.String,
            "affected_rows": pl.Int64,
        }
    )


def _unit_nonempty_count(unit_key: pl.Series) -> int:
    """Count rows whose unit key is non-null and non-empty (R ``sum(!is.na & nzchar)``)."""
    return int((unit_key.is_not_null() & (unit_key != "")).sum())
