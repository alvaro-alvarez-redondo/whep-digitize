"""Rule match-key encoding and target-update strategy resolution.

Two responsibilities:

* **Deterministic key handling** — collapse both sides of a rule comparison to comparable
  string keys so that missing values match each other and only each other. Two distinct
  internal tokens are involved, and both must be preserved byte-for-byte:

  - ``na_match_key`` (``"..NA_MATCH_KEY.."``) — every ``None`` folds to this before a
    match, so a null condition matches a null current value (and nothing else).
  - ``na_placeholder`` (``"..NA_INTERNAL.."``) — the token a null *target* value rides
    on through join operations (:func:`encode_target_rule_value` /
    :func:`decode_target_rule_value`).

* **Strategy configuration** — resolve, per target column, whether updates use
  ``last_rule_wins`` or ``concatenate``, plus the tokenized-target column set and the
  match-key normalization policy.

Match-key normalization reuses :func:`whep_digitize.setup.helpers.strings.normalize_string`
(NFD diacritic strip + non-alphanumeric collapse), so key correctness is guarded by that
policy's tests in ``tests/setup``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import polars as pl

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ConfigurationError
from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.strings import normalize_string

_CONSTANTS = get_pipeline_constants()
_NA_PLACEHOLDER = _CONSTANTS.na_placeholder
_NA_MATCH_KEY = _CONSTANTS.na_match_key
# The whitespace class used for blank detection: space, tab, CR, LF only. Declared explicitly
# because the polars/Python default strip also removes exotic Unicode whitespace, which would
# silently treat more values as blank than intended.
_R_TRIMWS_CHARS = " \t\r\n"
# Sentinel column name used to run a single-column expression over a bare Series.
_SERIES_SENTINEL = "__whep_value__"


@dataclass(frozen=True, slots=True)
class RuleMatchNormalizationSettings:
    """Resolved match-key normalization policy.

    Attributes:
        apply_once_before_stage: Normalize match keys once before the multi-pass loop.
        apply_each_pass: Re-normalize match keys on every pass.
        excluded_columns: Columns matched on raw (never normalized) values.
    """

    apply_once_before_stage: bool
    apply_each_pass: bool
    excluded_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetUpdateStrategyConfig:
    """Validated target-update strategy configuration.

    Attributes:
        default: Strategy used when no per-column override applies.
        supported: The full set of recognized strategy names.
        concatenate_delimiter: Delimiter for the ``concatenate`` strategy.
        by_column: Per-target-column strategy overrides.
    """

    default: str
    supported: tuple[str, ...]
    concatenate_delimiter: str
    by_column: Mapping[str, str]


def _map_series(series: pl.Series, build: Callable[[pl.Expr], pl.Expr]) -> pl.Series:
    """Run a single-column expression over ``series`` and return the resulting Series.

    Renames to a sentinel column so the transform works regardless of the input name
    (including the empty name), then restores the original name.

    Args:
        series: The input Series.
        build: Builds the output expression from the (sentinel) column expression.

    Returns:
        The transformed Series, carrying the input's name.
    """
    name = series.name
    result = (
        series.rename(_SERIES_SENTINEL)
        .to_frame()
        .select(build(pl.col(_SERIES_SENTINEL)).alias(_SERIES_SENTINEL))
        .to_series()
    )
    return result.rename(name)


def encode_target_rule_value(values: pl.Series, na_placeholder: str = _NA_PLACEHOLDER) -> pl.Series:
    """Encode target rule values, folding missing / blank values to the internal placeholder.

    Missing (``None``) and whitespace-only values become ``na_placeholder`` so a null target
    rides deterministically through join operations; every other value is kept as its string
    form.

    Args:
        values: Target values to encode.
        na_placeholder: The internal missing-value token.

    Returns:
        A string Series with placeholder-encoded values.
    """
    require(len(na_placeholder) >= 1, "na_placeholder must be a non-empty string")
    if values.len() == 0:
        return values.cast(pl.String)

    def build(column: pl.Expr) -> pl.Expr:
        string_column = column.cast(pl.String)
        is_blank = string_column.is_null() | (
            string_column.str.strip_chars(_R_TRIMWS_CHARS).str.len_chars() == 0
        )
        return pl.when(is_blank).then(pl.lit(na_placeholder)).otherwise(string_column)

    return _map_series(values, build)


def decode_target_rule_value(values: pl.Series, na_placeholder: str = _NA_PLACEHOLDER) -> pl.Series:
    """Decode the internal placeholder back to ``None`` before rule application.

    Args:
        values: Encoded values to decode.
        na_placeholder: The internal missing-value token.

    Returns:
        A string Series with ``na_placeholder`` reverted to ``None`` (other values unchanged).
    """
    require(len(na_placeholder) >= 1, "na_placeholder must be a non-empty string")
    if values.len() == 0:
        return values.cast(pl.String)

    def build(column: pl.Expr) -> pl.Expr:
        string_column = column.cast(pl.String)
        return (
            pl.when(string_column == na_placeholder)
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(string_column)
        )

    return _map_series(values, build)


def encode_rule_match_key(
    values: pl.Series,
    *,
    na_key: str = _NA_MATCH_KEY,
    apply_normalization: bool = True,
) -> pl.Series:
    """Build deterministic match keys, mapping missing values to an explicit token.

    Values are optionally normalized (NFD diacritic strip + non-alphanumeric collapse) to
    comparable string keys; every ``None`` then folds to ``na_key`` so that a null matches a
    null (and only a null) during comparison.

    Args:
        values: Values to encode.
        na_key: The token every missing value collapses to.
        apply_normalization: When true, normalize before keying; when false, key the raw
            string form (used for the excluded columns, e.g. ``year`` / ``value``).

    Returns:
        A string Series of match keys with no missing values.
    """
    require(len(na_key) >= 1, "na_key must be a non-empty string")
    if values.len() == 0:
        return values.cast(pl.String)
    string_values = values.cast(pl.String)
    encoded = normalize_string(string_values) if apply_normalization else string_values
    return encoded.fill_null(na_key)


def resolve_rule_match_normalization_settings() -> RuleMatchNormalizationSettings:
    """Return the centralized match-key normalization policy.

    Returns:
        The resolved :class:`RuleMatchNormalizationSettings`.
    """
    settings = _CONSTANTS.postpro.rule_match_normalization
    return RuleMatchNormalizationSettings(
        apply_once_before_stage=bool(settings.apply_once_before_stage),
        apply_each_pass=bool(settings.apply_each_pass),
        excluded_columns=tuple(settings.excluded_columns),
    )


def empty_last_rule_wins_overwrite_events_df() -> pl.DataFrame:
    """Return the standardized empty ``last_rule_wins`` overwrite-events frame.

    Returns:
        An empty frame with the overwrite-event schema (used to collect diagnostics when the
        ``last_rule_wins`` strategy discards competing candidates).
    """
    return pl.DataFrame(
        schema={
            "dataset_name": pl.String,
            "execution_stage": pl.String,
            "rule_file_identifier": pl.String,
            "column_source": pl.String,
            "column_target": pl.String,
            "row_id": pl.Int64,
            "candidate_count": pl.Int64,
            "unique_candidate_count": pl.Int64,
            "selected_value": pl.String,
            "candidate_values": pl.String,
        }
    )


def get_target_update_strategy_config() -> TargetUpdateStrategyConfig:
    """Validate and return the centralized target-update strategy configuration.

    Returns:
        The validated :class:`TargetUpdateStrategyConfig`.

    Raises:
        ConfigurationError: If the default strategy is not among the supported strategies.
    """
    strategy_config = _CONSTANTS.postpro.target_update_strategies
    if strategy_config.default not in strategy_config.supported:
        raise ConfigurationError(
            "invalid target-update strategy configuration: "
            "default strategy is not listed in supported strategies"
        )
    return TargetUpdateStrategyConfig(
        default=strategy_config.default,
        supported=tuple(strategy_config.supported),
        concatenate_delimiter=strategy_config.concatenate_delimiter,
        by_column=dict(strategy_config.by_column),
    )


def resolve_target_update_strategy(
    target_column: str,
    strategy_config: TargetUpdateStrategyConfig | None = None,
) -> str:
    """Resolve the update strategy for one target column, falling back to the default.

    Args:
        target_column: The target column name.
        strategy_config: Strategy configuration (defaults to the centralized config).

    Returns:
        The resolved strategy name.

    Raises:
        ConfigurationError: If the resolved strategy is not supported.
    """
    require(len(target_column) >= 1, "target_column must be a non-empty string")
    config = strategy_config if strategy_config is not None else get_target_update_strategy_config()

    resolved_strategy = config.by_column.get(target_column, config.default)

    if resolved_strategy not in config.supported:
        raise ConfigurationError(
            "unsupported target-update strategy configured: "
            f"column: {target_column}; strategy: {resolved_strategy}; "
            f"supported: {', '.join(config.supported)}"
        )
    return resolved_strategy


def resolve_last_rule_wins_unique_row_fast_path_enabled() -> bool:
    """Return whether the unique-row direct-update fast path is enabled for ``last_rule_wins``.

    Returns:
        The fast-path toggle.
    """
    return bool(_CONSTANTS.postpro.target_update_fast_path.last_rule_wins_unique_row_id)


def resolve_tokenized_target_condition_columns(
    strategy_config: TargetUpdateStrategyConfig | None = None,
) -> tuple[str, ...]:
    """Return the target columns whose condition matching treats ``;`` values as token sets.

    Tokenized matching is enabled for every ``concatenate``-strategy column and always for
    ``footnotes``. The result is unique and sorted by code point, so it is order-stable.

    Args:
        strategy_config: Strategy configuration (defaults to the centralized config).

    Returns:
        The sorted, unique tuple of tokenized target-condition columns.
    """
    config = strategy_config if strategy_config is not None else get_target_update_strategy_config()
    concatenate_columns = [
        column for column, strategy in config.by_column.items() if strategy == "concatenate"
    ]
    return tuple(sorted({*concatenate_columns, "footnotes"}))
