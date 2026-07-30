"""Directory construction — the Python port of R ``01-directories.R``.

Creates the import/export directory tree and the post-processing audit subtree
(``audit``, ``diagnostics``, ``templates``, ``runtime_cache``). Preserves the R
contract that the audit *root* (``data/postpro``) is created lazily by the
post-processing stage, not eagerly here.
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

    Mirrors the R logic: flatten all paths; for a path whose basename looks like a file
    (matches the file-extension pattern), use its parent directory; exclude the audit
    root; deduplicate and sort deterministically.

    Args:
        config: The resolved pipeline configuration.

    Returns:
        A sorted, unique list of directory paths to create.
    """
    audit_root = config.paths.data.audit.audit_root_dir.resolve()
    targets: set[Path] = set()
    for raw_path in _flatten_paths(config.paths):
        directory = raw_path.parent if _FILE_SUFFIX_RE.search(raw_path.name) else raw_path
        resolved = directory.resolve()
        if resolved == audit_root:
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


def ensure_output_directories(output_paths: list[Path]) -> None:
    """Create the parent directory of each output file path.

    Args:
        output_paths: File paths whose parent directories must exist before writing.
    """
    ensure_directories_exist([p.parent for p in output_paths])


def delete_directory_if_exists(
    directory: Path,
    *,
    tolerate_permission_errors: bool = True,
) -> bool:
    """Delete a directory tree if it exists.

    Args:
        directory: Directory to delete.
        tolerate_permission_errors: If ``True``, swallow permission/lock errors
            (mirrors the R behavior of continuing when the audit folder is locked).

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
