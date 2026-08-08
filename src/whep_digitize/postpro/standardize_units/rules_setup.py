"""Postpro / standardize_units — conversion-rule preparation.

Legacy-header aliasing, schema + conversion validation (normalized-key dedupe, finite
factor/offset, chained-rule guard), and materializing the numeric + normalized-key columns the
engine joins on.

The xlsx rule-file readers (``read_all_standardize_rule_files`` /
``read_standardize_rule_workbook`` / ``ensure_standardize_template_exists``) sit at the
orchestration IO boundary and live in the orchestration module, not here.
"""

from __future__ import annotations

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.numeric import coerce_numeric_series
from whep_digitize.setup.helpers.strings import normalize_string

_CONSTANTS = get_pipeline_constants()
_ALL_COMMODITY = _CONSTANTS.postpro.standardization.all_commodity_key
_REQUIRED_COLUMNS = _CONSTANTS.postpro.standardization.required_rule_columns
# Legacy rule headers -> canonical names.
_LEGACY_ALIASES: dict[str, str] = {
    "commodity": "commodity_key",
    "source_unit": "unit_source",
    "target_unit": "unit_target",
    "multiplier": "unit_factor",
    "addend": "unit_offset",
    "from_unit": "unit_source",
    "to_unit": "unit_target",
    "factor": "unit_factor",
    "offset": "unit_offset",
}


def validate_rule_schema(
    rule_df: pl.DataFrame, required_columns: tuple[str, ...], rule_label: str
) -> None:
    """Assert every required column is present and free of missing values.

    Args:
        rule_df: The rule table (at least one row).
        required_columns: The columns that must be present and non-null.
        rule_label: A label used in error messages.

    Raises:
        ValidationError: If the table is empty, a required column is missing, or a required
            column contains a null.
    """
    require(rule_df.height >= 1, "rule table must have at least one row")
    require(len(required_columns) >= 1, "required_columns must be non-empty")
    require(len(rule_label) >= 1, "rule_label must be a non-empty string")

    missing = [column for column in required_columns if column not in rule_df.columns]
    if missing:
        raise ValidationError(
            f"Missing required columns in {rule_label} rules: {', '.join(missing)}"
        )

    with_na = [column for column in required_columns if rule_df.get_column(column).null_count() > 0]
    if with_na:
        raise ValidationError(
            f"Found missing values in required {rule_label} rule columns: {', '.join(with_na)}"
        )


def normalize_conversion_rule_columns(conversion_df: pl.DataFrame) -> pl.DataFrame:
    """Rename legacy conversion-rule headers to the canonical names.

    a legacy alias is renamed only
    when its canonical target is not already present; two aliases mapping to the same canonical
    column are rejected (they would create a duplicate-named column).

    Args:
        conversion_df: The raw conversion-rule table.

    Returns:
        The table with legacy headers renamed to canonical names.

    Raises:
        ValidationError: If two legacy aliases would rename to the same canonical column.
    """
    columns = conversion_df.columns
    to_rename = [
        (legacy, canonical)
        for legacy, canonical in _LEGACY_ALIASES.items()
        if legacy in columns and canonical not in columns
    ]
    targets = [canonical for _, canonical in to_rename]
    colliding = [target for target in dict.fromkeys(targets) if targets.count(target) > 1]
    if colliding:
        conflicting = [legacy for legacy, canonical in to_rename if canonical in colliding]
        raise ValidationError(
            "conversion rule columns map multiple legacy aliases to the same canonical column: "
            f"{', '.join(colliding)} (conflicting source columns: {', '.join(conflicting)})"
        )
    return conversion_df.rename(dict(to_rename)) if to_rename else conversion_df


def validate_conversion_rules(conversion_df: pl.DataFrame) -> None:
    """Validate the conversion-rule schema, key uniqueness, finiteness, and chained-rule guard.

    Uniqueness and chained detection use the
    **normalized** keys the engine joins on (so case/punctuation variants cannot slip through).

    Args:
        conversion_df: The conversion-rule table (canonical headers, at least one row).

    Raises:
        ValidationError: On schema failure, duplicate normalized ``(commodity_key, unit_source)``
            keys, a non-finite factor/offset, or chained specific-commodity conversions.
    """
    require(conversion_df.height >= 1, "conversion rules must have at least one row")
    validate_rule_schema(conversion_df, _REQUIRED_COLUMNS, "standardization conversion")

    commodity_key = normalize_string(conversion_df.get_column("commodity_key").cast(pl.String))
    unit_source_key = normalize_string(conversion_df.get_column("unit_source").cast(pl.String))
    unit_target_key = normalize_string(conversion_df.get_column("unit_target").cast(pl.String))

    duplicates = (
        pl.DataFrame({"commodity_match_key": commodity_key, "unit_source_key": unit_source_key})
        .group_by(["commodity_match_key", "unit_source_key"])
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicates.height > 0:
        raise ValidationError(
            "conversion rules contain duplicate (commodity_key, unit_source) definitions after "
            "normalization"
        )

    unit_factor = coerce_numeric_series(conversion_df.get_column("unit_factor"))
    unit_offset = coerce_numeric_series(conversion_df.get_column("unit_offset"))
    if not bool(unit_factor.is_finite().fill_null(value=False).all()):
        raise ValidationError("conversion unit_factor values must be finite")
    if not bool(unit_offset.is_finite().fill_null(value=False).all()):
        raise ValidationError("conversion unit_offset values must be finite")

    source_pairs = pl.DataFrame(
        {"commodity_match_key": commodity_key, "unit_match_key": unit_source_key}
    ).unique()
    target_pairs = pl.DataFrame(
        {"commodity_match_key": commodity_key, "unit_match_key": unit_target_key}
    ).unique()
    source_specific = source_pairs.filter(pl.col("commodity_match_key") != _ALL_COMMODITY)
    target_specific = target_pairs.filter(pl.col("commodity_match_key") != _ALL_COMMODITY)
    chained = source_specific.join(
        target_specific, on=["commodity_match_key", "unit_match_key"], how="inner"
    )
    if chained.height > 0:
        raise ValidationError(
            "conversion rules create chained conversions for the same commodity; this can trigger "
            "double conversion on repeated runs"
        )


def prepare_standardize_rules(raw_rules_df: pl.DataFrame) -> pl.DataFrame:
    """Normalize headers, validate, and materialize the engine's numeric + key columns.

    adds ``unit_factor_num`` /
    ``unit_offset_num`` (coerced) and ``commodity_match_key`` / ``unit_source_key`` (normalized).

    Args:
        raw_rules_df: The raw (or merged) conversion-rule table.

    Returns:
        The prepared rule table (empty input is returned normalized, without the extra columns).
    """
    prepared = normalize_conversion_rule_columns(raw_rules_df)
    if prepared.height == 0:
        return prepared

    validate_conversion_rules(prepared)
    return prepared.with_columns(
        coerce_numeric_series(prepared.get_column("unit_factor")).alias("unit_factor_num"),
        coerce_numeric_series(prepared.get_column("unit_offset")).alias("unit_offset_num"),
        normalize_string(prepared.get_column("commodity_key").cast(pl.String)).alias(
            "commodity_match_key"
        ),
        normalize_string(prepared.get_column("unit_source").cast(pl.String)).alias(
            "unit_source_key"
        ),
    )
