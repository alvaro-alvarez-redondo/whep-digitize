"""Shared post-processing stage metadata — the Python port of ``21-stage-definitions.R``.

Small reusable accessors for the canonical rule schema and the ``clean`` / ``harmonize`` stage
identities, used across the rule engine (schema validation, dictionary construction, target
application). All values come from :func:`get_pipeline_constants`.

R source: ``r/2-postpro_pipeline/21-postpro_utilities/21-stage-definitions.R``
(``get_canonical_rule_columns``, ``get_postpro_stage_names``, ``validate_postpro_stage_name``,
``get_stage_target_value_column``, ``get_stage_source_value_column``). The R stage-payload
bundle cache (``.stage_payload_bundle_cache``) belongs to ``21-runtime-cache.R`` and is ported
separately.
"""

from __future__ import annotations

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError

_CONSTANTS = get_pipeline_constants()


def get_canonical_rule_columns() -> tuple[str, ...]:
    """Return the unified canonical rule columns used by both post-processing stages.

    Returns:
        The six canonical column names, in canonical order.
    """
    return _CONSTANTS.postpro.canonical_rule_columns


def get_postpro_stage_names() -> tuple[str, ...]:
    """Return the supported post-processing stage names in deterministic order.

    Returns:
        ``("clean", "harmonize")``.
    """
    return _CONSTANTS.postpro.stage_names


def validate_postpro_stage_name(stage_name: str) -> str:
    """Validate and return a post-processing stage name.

    Note:
        R uses ``match.arg`` (which also accepts unambiguous abbreviations); the pipeline always
        passes a full stage name, so this port matches exactly and rejects anything else.

    Args:
        stage_name: The stage label to validate.

    Returns:
        The validated stage name.

    Raises:
        ValidationError: If ``stage_name`` is not a supported stage.
    """
    supported = get_postpro_stage_names()
    if stage_name not in supported:
        raise ValidationError(
            f"unsupported post-processing stage '{stage_name}'; expected one of: "
            f"{', '.join(supported)}"
        )
    return stage_name


def get_stage_target_value_column(stage_name: str) -> str:
    """Return the unified target value column name for a stage.

    Args:
        stage_name: The stage label (validated).

    Returns:
        The target value column name (``"value_target"``).
    """
    validate_postpro_stage_name(stage_name)
    return _CONSTANTS.postpro.stage_target_value_column


def get_stage_source_value_column(stage_name: str) -> str:
    """Return the unified source value column name for a stage.

    Args:
        stage_name: The stage label (validated).

    Returns:
        The source value column name (``"value_source"``).
    """
    validate_postpro_stage_name(stage_name)
    return _CONSTANTS.postpro.stage_source_value_column
