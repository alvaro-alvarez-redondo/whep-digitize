"""Directory construction for a pipeline run.

Creates the import/export directory tree and the post-processing audit subtree
(``audit``, ``templates``). By contract the audit *root* (``data/postpro``) is created
lazily by the post-processing stage, not eagerly here. Two subdirectories are excluded from
eager creation entirely, since nothing needs them to exist ahead of time:

* ``runtime_cache`` — exists only when the rule-payload cache is enabled and actually
  persists an entry (see ``postpro.utilities.payload_cache._persist_bundle_to_disk``).
* ``diagnostics`` — currently unused; no code path writes into it.
* ``duplicates`` — created by the post-processing duplicate audit when it writes its TSVs
  (see ``postpro.diagnostics.duplicates``), so a bootstrap-only run never creates it.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import fields, is_dataclass
from pathlib import Path

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants

_FILE_SUFFIX_RE = re.compile(get_pipeline_constants().patterns.file_extension, re.IGNORECASE)


def _flatten_paths(node: object) -> list[Path]:
    """Recursively collect every :class:`~pathlib.Path` leaf under a Config path tree.

    Args:
        node: A dataclass node, ``Path``, or nested structure.

    Returns:
        All ``Path`` values found, in traversal order.
    """
    if isinstance(node, Path):
        return [node]
    if is_dataclass(node) and not isinstance(node, type):
        collected: list[Path] = []
        for f in fields(node):
            collected.extend(_flatten_paths(getattr(node, f.name)))
        return collected
    return []


def _resolve_directory_targets(config: Config) -> list[Path]:
    """Resolve the set of directories to create from a config's path tree.

    Flattens all paths; for a path whose basename looks like a file (matches the
    file-extension pattern), uses its parent directory; excludes the audit root, the
    runtime-cache directory, and the diagnostics directory; deduplicates and sorts
    deterministically.

    ``runtime_cache_dir`` is excluded deliberately: the rule-payload cache is off by default,
    and creating its directory on every run regardless of whether it is ever used would leave
    an empty ``runtime_cache`` folder in the output tree. It is created lazily, only when the
    cache is enabled and a bundle is actually persisted to disk (see
    ``postpro.utilities.payload_cache``).

    ``diagnostics_dir`` is excluded for the same reason: nothing currently writes into it, so
    eagerly creating it would leave a permanently empty ``diagnostics`` folder. If a future
    writer needs it, that writer should create it lazily, the way the runtime cache does.

    ``duplicates_dir`` is excluded because the post-processing duplicate audit creates it when
    it writes, so a stage-0-only run (``bootstrap``) leaves no empty folder behind.

    Args:
        config: The resolved pipeline configuration.

    Returns:
        A sorted, unique list of directory paths to create.
    """
    audit = config.paths.data.audit
    excluded = {
        audit.audit_root_dir.resolve(),
        audit.runtime_cache_dir.resolve(),
        audit.diagnostics_dir.resolve(),
        audit.duplicates_dir.resolve(),
    }
    targets: set[Path] = set()
    for raw_path in _flatten_paths(config.paths):
        directory = raw_path.parent if _FILE_SUFFIX_RE.search(raw_path.name) else raw_path
        resolved = directory.resolve()
        if resolved in excluded:
            continue
        targets.add(resolved)
    return sorted(targets)


def ensure_directories_exist(directories: list[Path]) -> list[Path]:
    """Create each directory (with parents) if it does not exist.

    Args:
        directories: Directories to create.

    Returns:
        The unique, sorted directories, after creation.
    """
    unique_sorted = sorted({d.resolve() for d in directories})
    for directory in unique_sorted:
        directory.mkdir(parents=True, exist_ok=True)
    return unique_sorted


def delete_directory_if_exists(
    directory: Path,
    *,
    tolerate_permission_errors: bool = True,
) -> bool:
    """Delete a directory tree if it exists.

    Args:
        directory: Directory to delete.
        tolerate_permission_errors: If ``True``, swallow permission/lock errors so the run
            continues when the audit folder is locked (e.g. open in Excel).

    Returns:
        ``True`` if the directory was deleted, ``False`` if it did not exist or a
        tolerated error occurred.
    """
    if not directory.exists():
        return False
    try:
        shutil.rmtree(directory)
    except (PermissionError, OSError):
        if tolerate_permission_errors:
            return False
        raise
    return True


def create_required_directories(config: Config) -> list[Path]:
    """Create the full pipeline directory tree for a run.

    Args:
        config: The resolved pipeline configuration.

    Returns:
        The directories that were ensured to exist (sorted, unique).
    """
    return ensure_directories_exist(_resolve_directory_targets(config))
