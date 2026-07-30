"""Postpro / diagnostics — preflight checks.

The Python port of ``r/2-postpro_pipeline/25-postpro_diagnostics/25-preflight.R``: deterministic
checks that the rule directories exist, the rule files follow the ``clean_`` / ``harmonize_``
naming convention, and the dataset carries the expected columns — collected into a result and
optionally asserted (aborting with the collected issues).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import WhepError

_RULE_EXTENSION_RE = re.compile(r"\.(xlsx|xls|csv)$")
_CLEAN_PATTERN_RE = re.compile(r"^clean_.*\.(xlsx|xls|csv)$")
_HARMONIZE_PATTERN_RE = re.compile(r"^harmonize_.*\.(xlsx|xls|csv)$")
_DEFAULT_EXPECTED_COLUMNS = ("unit", "value", "commodity")


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Result of :func:`collect_postpro_preflight` (R ``list(passed, issues, checks)``).

    Attributes:
        passed: Whether every check passed (no issues).
        issues: The human-readable issue messages (empty when passed).
        checks: The per-check boolean flags.
    """

    passed: bool
    issues: tuple[str, ...]
    checks: Mapping[str, bool]


def _rule_files(directory: Path) -> list[Path]:
    """Return files under ``directory`` whose name ends in a rule extension (empty if absent)."""
    if not directory.is_dir():
        return []
    return [
        entry
        for entry in directory.iterdir()
        if entry.is_file() and _RULE_EXTENSION_RE.search(entry.name)
    ]


def collect_postpro_preflight(
    config: Config,
    dataset_columns: Sequence[str],
    expected_columns: Sequence[str] = _DEFAULT_EXPECTED_COLUMNS,
) -> PreflightResult:
    """Run the post-processing preflight checks.

    The Python port of R ``collect_postpro_preflight``.

    Args:
        config: The resolved pipeline configuration.
        dataset_columns: The input dataset's columns.
        expected_columns: The columns the run requires.

    Returns:
        The :class:`PreflightResult`.
    """
    cleaning_dir = config.paths.data.import_.cleaning
    harmonization_dir = config.paths.data.import_.harmonization
    audit = config.paths.data.audit

    checks: dict[str, bool] = {
        "cleaning_dir_exists": cleaning_dir.is_dir(),
        "harmonize_dir_exists": harmonization_dir.is_dir(),
        "templates_dir_exists": audit.templates_dir.is_dir(),
        "diagnostics_dir_exists": audit.diagnostics_dir.is_dir(),
    }
    issues: list[str] = []
    if not checks["cleaning_dir_exists"]:
        issues.append("[clean stage] missing clean directory")
    if not checks["harmonize_dir_exists"]:
        issues.append("[harmonize stage] missing harmonize directory")
    if not checks["templates_dir_exists"]:
        issues.append("[postpro root] missing templates directory")
    if not checks["diagnostics_dir_exists"]:
        issues.append("[postpro root] missing diagnostics directory")

    checks["cleaning_pattern_ok"] = all(
        _CLEAN_PATTERN_RE.match(entry.name) for entry in _rule_files(cleaning_dir)
    )
    checks["harmonize_pattern_ok"] = all(
        _HARMONIZE_PATTERN_RE.match(entry.name) for entry in _rule_files(harmonization_dir)
    )
    if not checks["cleaning_pattern_ok"]:
        issues.append("[clean stage] invalid clean file naming pattern (expected prefix: clean_)")
    if not checks["harmonize_pattern_ok"]:
        issues.append(
            "[harmonize stage] invalid harmonize file naming pattern (expected prefix: harmonize_)"
        )

    dataset_column_set = set(dataset_columns)
    missing = [column for column in expected_columns if column not in dataset_column_set]
    checks["has_expected_columns"] = not missing
    if missing:
        issues.append(f"[run_postpro_pipeline] missing expected columns: {', '.join(missing)}")

    return PreflightResult(passed=not issues, issues=tuple(issues), checks=checks)


def assert_postpro_preflight(preflight_result: PreflightResult) -> None:
    """Abort when preflight failed, listing the collected issues.

    The Python port of R ``assert_postpro_preflight``.

    Args:
        preflight_result: The result from :func:`collect_postpro_preflight`.

    Raises:
        WhepError: If ``preflight_result.passed`` is false.
    """
    if not preflight_result.passed:
        raise WhepError(
            "Post-processing preflight checks failed. " + "; ".join(preflight_result.issues)
        )
