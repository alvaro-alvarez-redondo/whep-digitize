"""Crash-recovery checkpoints — the Python port of ``02-checkpoints.R``.

The R pipeline optionally persists per-stage results as ``.rds`` for crash recovery,
gated by ``whep.checkpointing.enabled`` (default off). The Python port prefers Parquet
for :class:`polars.DataFrame` results (portable, fast) and falls back to pickle for
composite objects. Checkpointing is opt-in via ``RuntimeOptions.checkpointing_enabled``.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants


def _checkpoint_dir(config: Config) -> Path:
    """Return the checkpoints directory (``data/.checkpoints``) for a run."""
    constants = get_pipeline_constants()
    return config.project_root / constants.paths.data_dir / constants.paths.checkpoints_dir


def checkpoint_path(name: str, config: Config, *, is_frame: bool) -> Path:
    """Return the checkpoint file path for ``name`` (``.parquet`` or ``.pkl``).

    Args:
        name: Checkpoint name (e.g. ``"import_pipeline"``).
        config: The pipeline configuration.
        is_frame: Whether the payload is a :class:`polars.DataFrame`.

    Returns:
        The checkpoint file path.
    """
    suffix = ".parquet" if is_frame else ".pkl"
    return _checkpoint_dir(config) / f"{name}{suffix}"


def save_checkpoint(name: str, data: Any, config: Config, *, enabled: bool) -> Path | None:
    """Persist a checkpoint if checkpointing is enabled.

    Args:
        name: Checkpoint name.
        data: Payload — a :class:`polars.DataFrame` (Parquet) or any picklable object.
        config: The pipeline configuration.
        enabled: Gate flag (from ``RuntimeOptions.checkpointing_enabled``).

    Returns:
        The written path, or ``None`` if checkpointing is disabled.
    """
    if not enabled:
        return None
    is_frame = isinstance(data, pl.DataFrame)
    path = checkpoint_path(name, config, is_frame=is_frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_frame:
        data.write_parquet(path)
    else:
        with path.open("wb") as handle:
            pickle.dump(data, handle)
    return path


def load_checkpoint(name: str, config: Config, *, enabled: bool) -> Any | None:
    """Load a checkpoint if enabled and present.

    Args:
        name: Checkpoint name.
        config: The pipeline configuration.
        enabled: Gate flag (from ``RuntimeOptions.checkpointing_enabled``).

    Returns:
        The restored payload, or ``None`` if disabled or absent.
    """
    if not enabled:
        return None
    frame_path = checkpoint_path(name, config, is_frame=True)
    if frame_path.exists():
        return pl.read_parquet(frame_path)
    object_path = checkpoint_path(name, config, is_frame=False)
    if object_path.exists():
        # Trusted, locally-written checkpoint (opt-in, under the project data dir).
        with object_path.open("rb") as handle:
            return pickle.load(handle)
    return None


def clear_checkpoints(config: Config) -> None:
    """Delete all checkpoint files for a run.

    Args:
        config: The pipeline configuration.
    """
    directory = _checkpoint_dir(config)
    if not directory.exists():
        return
    for path in directory.iterdir():
        if path.suffix in {".parquet", ".pkl"}:
            path.unlink()
