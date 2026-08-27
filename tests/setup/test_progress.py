"""Tests for the gated stage-progress helper."""

from __future__ import annotations

import io
import sys
import time

import pytest
from rich.console import Console
from rich.progress import Task

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.progress import (
    StageProgress,
    _is_modern_terminal,
    _resolve_glyphs,
    _StageBarColumn,
    _StageSpinnerColumn,
    stage_progress,
)
from whep_digitize.setup.helpers.progress import (
    _build_progress as build_progress,
)

_CONSTANTS = get_pipeline_constants().progress
_MODERN_VARS = ("WT_SESSION", "WT_PROFILE_ID", "TERM_PROGRAM", "ConEmuANSI")


class _Utf8Sink(io.StringIO):
    encoding = "utf-8"


class _Cp1252Sink(io.StringIO):
    encoding = "cp1252"


def _console(sink: io.StringIO, width: int = 80) -> Console:
    """A capture console that reports itself as a terminal of exactly ``width`` columns."""
    return Console(
        file=sink, force_terminal=True, width=width, color_system=None, legacy_windows=False
    )


def _render_line(sink: io.StringIO, console: Console, completed: int, item: str) -> str:
    """Render one static frame of the stage bar and return the line, without the live loop."""
    progress = build_progress("ingest", console)
    task_id = progress.add_task("ingest", total=100, item=item)
    progress.update(task_id, completed=completed, item=item)
    # Rendered outside the live context on purpose: while a live display is running rich
    # buffers prints and replays them, so a captured frame would come back empty.
    console.print(progress.get_renderable())
    return sink.getvalue().rstrip("\n")


def _bar_column(console: Console, label: str = "ingest") -> _StageBarColumn:
    progress = build_progress(label, console)
    return next(c for c in progress.columns if isinstance(c, _StageBarColumn))


def _task_at(console: Console, completed: float, total: float = 100, label: str = "ingest") -> Task:
    progress = build_progress(label, console)
    task_id = progress.add_task(label, total=total, item="")
    progress.update(task_id, completed=completed)
    return progress.tasks[0]


# --------------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------------


def test_stage_progress_disabled_is_inert() -> None:
    with stage_progress("stage", total=3, enabled=False) as progress:
        assert isinstance(progress, StageProgress)
        # step / pulse are no-ops when disabled (no display, no error).
        progress.step("first")
        progress.pulse("mid")
        progress.step()


def test_stage_progress_enabled_runs_without_error() -> None:
    with stage_progress("stage", total=2, enabled=True) as progress:
        assert isinstance(progress, StageProgress)
        progress.step("one")
        progress.pulse("working")
        progress.step("two")


def test_stage_progress_zero_total_does_not_divide_by_zero() -> None:
    # A stage that declares no advances still gets a usable bar (total is floored at 1).
    with stage_progress("stage", total=0, enabled=True) as progress:
        progress.pulse("nothing to do")


# --------------------------------------------------------------------------------------------
# Capability gating
# --------------------------------------------------------------------------------------------


def test_glyphs_use_block_elements_when_the_encoding_allows_them() -> None:
    glyphs = _resolve_glyphs(_console(_Utf8Sink()))
    assert (glyphs.fill, glyphs.track, glyphs.partial) == ("█", "░", "▌")


def test_glyphs_fall_back_to_ascii_on_a_cp1252_console() -> None:
    # cp1252 cannot encode the block elements; the bar must degrade rather than crash.
    glyphs = _resolve_glyphs(_console(_Cp1252Sink()))
    assert (glyphs.fill, glyphs.track, glyphs.partial) == ("#", "-", "")
    assert glyphs.done == "*"


def test_spinner_and_done_mark_need_a_positively_identified_modern_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Plain cmd.exe encodes UTF-8 fine, but conhost's fonts have no braille and no check
    # mark: it gets the CP437 half-block rotation and the ASCII done mark instead.
    monkeypatch.setattr(sys, "platform", "win32")
    for name in _MODERN_VARS:
        monkeypatch.delenv(name, raising=False)
    plain = _resolve_glyphs(_console(_Utf8Sink()))
    assert plain.spinner == ("▌", "▀", "▐", "▄")
    assert plain.done == "*"

    # A known-modern terminal gets braille and the check mark.
    monkeypatch.setenv("WT_SESSION", "1")
    modern = _resolve_glyphs(_console(_Utf8Sink()))
    assert modern.spinner[0] == "⠋"
    assert len(modern.spinner) == 10
    assert modern.done == "✓"


def test_spinner_falls_back_to_ascii_when_unicode_is_unencodable() -> None:
    # cp1252 cannot encode the half blocks either, so the spinner drops to ASCII.
    glyphs = _resolve_glyphs(_console(_Cp1252Sink()))
    assert glyphs.spinner == ("|", "/", "-", chr(92))


def test_spinner_advances_with_the_task_clock_and_marks_completion() -> None:
    console = _console(_Utf8Sink())
    frames = ("a", "b", "c")
    column = _StageSpinnerColumn(
        frames=frames, done="!", accent="cyan", finished_style="green", interval=0.1
    )
    running = _task_at(console, 10)
    # The frame index is derived from the clock, so successive repaints cycle the frames.
    seen = set()
    for _ in range(12):
        seen.add(column.render(running).plain)
        time.sleep(0.03)
    assert seen <= set(frames)
    assert len(seen) > 1, "the spinner never advanced"

    finished = column.render(_task_at(console, 100))
    assert finished.plain == "!"
    assert finished.style == "green"


def test_every_console_is_modern_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    for name in _MODERN_VARS:
        monkeypatch.delenv(name, raising=False)
    assert _is_modern_terminal() is True


# --------------------------------------------------------------------------------------------
# The bar column
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("completed", "expected_full"),
    [(0, 0), (50, 11), (100, 22)],
)
def test_bar_fills_in_proportion_to_completion(completed: int, expected_full: int) -> None:
    console = _console(_Utf8Sink())
    rendered = _bar_column(console).render(_task_at(console, completed))
    assert rendered.plain.count("█") == expected_full


def test_bar_shows_a_half_block_when_the_fill_lands_mid_cell() -> None:
    console = _console(_Utf8Sink())
    column = _bar_column(console)
    # 25/100 of 22 cells = 5.5 cells: five full blocks plus a half.
    mid = column.render(_task_at(console, 25))
    assert mid.plain.startswith("█████▌")
    # A fill landing under the half-cell mark rounds down to whole blocks only
    # (20/100 of 22 cells = 4.4 cells).
    low = column.render(_task_at(console, 20))
    assert low.plain.startswith("████░")


def test_bar_is_always_exactly_the_configured_width() -> None:
    console = _console(_Utf8Sink())
    column = _bar_column(console)
    for completed in (0, 1, 25, 50, 99, 100):
        assert len(column.render(_task_at(console, completed)).plain) == _CONSTANTS.bar_width


def test_finished_bar_is_full_and_carries_the_finished_style() -> None:
    console = _console(_Utf8Sink())
    rendered = _bar_column(console).render(_task_at(console, 100))
    assert rendered.plain == "█" * _CONSTANTS.bar_width
    assert rendered.style == _CONSTANTS.finished_style


def test_running_bar_carries_the_stage_accent() -> None:
    console = _console(_Utf8Sink())
    rendered = _bar_column(console, "postpro").render(_task_at(console, 40, label="postpro"))
    assert rendered.style == _CONSTANTS.stage_styles["postpro"]


def test_unknown_stage_label_falls_back_to_the_default_accent() -> None:
    console = _console(_Utf8Sink())
    rendered = _bar_column(console, "mystery").render(_task_at(console, 40, label="mystery"))
    assert rendered.style == _CONSTANTS.default_stage_style


# --------------------------------------------------------------------------------------------
# Layout: the line must never wrap, because a wrapped line breaks the in-place redraw
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [60, 80, 100, 120, 200])
def test_rendered_line_never_exceeds_the_console_width(width: int) -> None:
    sink = _Utf8Sink()
    line = _render_line(
        sink,
        _console(sink, width=width),
        completed=63,
        item="transforming a_very_long_workbook_name_that_would_overflow.xlsx",
    )
    assert len(line) <= width


@pytest.mark.parametrize(("width", "expected_bar"), [(50, 10), (55, 15), (60, 20), (80, 22)])
def test_narrow_console_shrinks_the_bar_rather_than_clipping_it(
    width: int, expected_bar: int
) -> None:
    # As the console narrows the item column squeezes to its minimum first, then the bar
    # gives way down to its floor -- it is never cut off by the ellipsis overflow.
    console = _console(_Utf8Sink(), width=width)
    rendered = _bar_column(console).render(_task_at(console, 100))
    assert len(rendered.plain) == expected_bar
    assert len(rendered.plain) >= _CONSTANTS.bar_min_width
    assert "…" not in rendered.plain


def test_wide_console_keeps_the_bar_bounded() -> None:
    console = _console(_Utf8Sink(), width=200)
    rendered = _bar_column(console).render(_task_at(console, 100))
    assert len(rendered.plain) == _CONSTANTS.bar_width


def test_long_item_label_is_ellipsized_not_wrapped() -> None:
    sink = _Utf8Sink()
    line = _render_line(
        sink,
        _console(sink, width=80),
        completed=10,
        item="reading a_workbook_name_far_longer_than_the_item_column.xlsx",
    )
    assert "\n" not in line
    assert "…" in line


# --------------------------------------------------------------------------------------------
# Advancing
# --------------------------------------------------------------------------------------------


def test_step_advances_and_pulse_only_relabels() -> None:
    console = _console(_Utf8Sink())
    progress = build_progress("ingest", console)
    task_id = progress.add_task("ingest", total=4, item="")
    handle = StageProgress(progress, task_id)

    handle.step("one")
    handle.step("two")
    assert progress.tasks[0].completed == 2
    assert progress.tasks[0].fields["item"] == "two"

    handle.pulse("still two")
    assert progress.tasks[0].completed == 2
    assert progress.tasks[0].fields["item"] == "still two"


def test_bar_closes_at_full_even_when_the_stage_under_advances() -> None:
    # A stage that declares 10 units but advances 3 must still leave a finished bar behind.
    with stage_progress("ingest", total=10, enabled=True) as handle:
        handle.step("one")
        handle.step("two")
        handle.step("three")
        progress = handle._progress
        task_id = handle._task
    assert progress is not None
    assert task_id is not None
    task = progress.tasks[0]
    assert task.completed == task.total
    assert task.finished
