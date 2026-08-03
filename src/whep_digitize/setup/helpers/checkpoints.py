"""Crash-recovery checkpoints — optional persistence of per-stage results.

Per-stage results can be persisted so a crashed run resumes instead of restarting: Parquet
for :class:`polars.DataFrame` results (portable, fast), falling back to pickle for
composite objects. Checkpointing is opt-in via ``RuntimeOptions.checkpointing_enabled``
(default off).

The import stage is the only wired caller
(:func:`whep_digitize.ingest.runner.run_import_pipeline`); postpro and export do not
checkpoint. Save and restore each emit a console status line.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import polars as pl

from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.console import alert_info, alert_success


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
    checkpoints = get_pipeline_constants().checkpoints
    suffix = checkpoints.frame_suffix if is_frame else checkpoints.object_suffix
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
    alert_info(get_pipeline_constants().checkpoints.saved_message.format(path=path))
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
    restored_message = get_pipeline_constants().checkpoints.restored_message
    frame_path = checkpoint_path(name, config, is_frame=True)
    if frame_path.exists():
        frame = pl.read_parquet(frame_path)
        alert_success(restored_message.format(path=frame_path))
        return frame
    object_path = checkpoint_path(name, config, is_frame=False)
    if object_path.exists():
        # Trusted, locally-written checkpoint (opt-in, under the project data dir).
        with object_path.open("rb") as handle:
            payload = pickle.load(handle)
        alert_success(restored_message.format(path=object_path))
        return payload
    return None


def clear_checkpoints(config: Config) -> None:
    """Delete all checkpoint files for a run.

    Args:
        config: The pipeline configuration.
    """
    checkpoints = get_pipeline_constants().checkpoints
    directory = _checkpoint_dir(config)
    if not directory.exists():
        return
    for path in directory.iterdir():
        if path.suffix in {checkpoints.frame_suffix, checkpoints.object_suffix}:
            path.unlink()
