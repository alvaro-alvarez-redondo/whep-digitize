"""Tests for the gated stage-progress helper."""

from __future__ import annotations

from whep_digitize.setup.helpers.progress import StageProgress, stage_progress


def test_stage_progress_disabled_is_inert() -> None:
    with stage_progress("stage", total=3, enabled=False) as progress:
        assert isinstance(progress, StageProgress)
        # step / pulse are no-ops when disabled (no rich display, no error).
        progress.step("first")
        progress.pulse("mid")
        progress.step()


def test_stage_progress_enabled_runs_without_error() -> None:
    with stage_progress("stage", total=2, enabled=True) as progress:
        assert isinstance(progress, StageProgress)
        progress.step("one")
        progress.pulse("working")
        progress.step("two")
