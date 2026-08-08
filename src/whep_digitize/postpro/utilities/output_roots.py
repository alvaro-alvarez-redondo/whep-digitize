"""Postpro / utilities — audit output-root resolution.

Resolve the post-processing output subtree (``audit`` / ``diagnostics`` / ``templates`` /
``runtime_cache``) from the config, and create it on disk. The typed
:class:`~whep_digitize.setup.config.Config` has already resolved every directory, so these
helpers read them directly and never invent a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whep_digitize.setup.config import Config
from whep_digitize.setup.directories import ensure_directories_exist
from whep_digitize.setup.helpers.assertions import require


@dataclass(frozen=True, slots=True)
class PostproOutputPaths:
    """The post-processing output root plus its four sub-directories.

    Attributes:
        audit_root_dir: The post-processing output root (``data/postpro``).
        audit_dir: The data-validation audit directory.
        diagnostics_dir: The diagnostics directory.
        templates_dir: The rule-template directory.
        runtime_cache_dir: The rule-payload runtime-cache directory.
    """

    audit_root_dir: Path
    audit_dir: Path
    diagnostics_dir: Path
    templates_dir: Path
    runtime_cache_dir: Path


def get_postpro_output_paths(config: Config) -> PostproOutputPaths:
    """Resolve the post-processing output directories from ``config``.

    Args:
        config: The resolved pipeline configuration.

    Returns:
        The resolved :class:`PostproOutputPaths` (no directories are created).

    Raises:
        ValidationError: If the audit root path is blank.
    """
    audit = config.paths.data.audit
    require(len(str(audit.audit_root_dir)) >= 1, "config audit_root_dir must be a non-empty path")
    return PostproOutputPaths(
        audit_root_dir=audit.audit_root_dir,
        audit_dir=audit.audit_dir,
        diagnostics_dir=audit.diagnostics_dir,
        templates_dir=audit.templates_dir,
        runtime_cache_dir=audit.runtime_cache_dir,
    )


def initialize_postpro_output_root(config: Config) -> PostproOutputPaths:
    """Resolve and create the post-processing output subtree.

    Creates the root and each of the four output directories (with parents) and returns them.

    Args:
        config: The resolved pipeline configuration.

    Returns:
        The created :class:`PostproOutputPaths`.
    """
    paths = get_postpro_output_paths(config)
    ensure_directories_exist(
        [
            paths.audit_root_dir,
            paths.audit_dir,
            paths.diagnostics_dir,
            paths.templates_dir,
            paths.runtime_cache_dir,
        ]
    )
    return paths
