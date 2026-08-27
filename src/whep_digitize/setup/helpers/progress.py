"""Stage progress bars — a ``rich`` live display, one bar per pipeline stage.

Each stage runner wraps its work in :func:`stage_progress`, a context manager that yields a
:class:`StageProgress`. ``step`` advances the bar by one unit; ``pulse`` updates the trailing
item label without advancing. The long ingest read advances the bar once per file (``step`` is
its per-file callback), so the bar fills smoothly across the whole run.

A stage renders as one fixed-width line, redrawn in place by ``rich``::

    * ingest    <bar> 64%  0:00:12  reading fao_1961_trade_23.xlsx

A background refresh thread repaints it ~10 times a second, so the spinner turns and the
elapsed timer ticks even while a single step is busy on a slow workbook — the bar never looks
frozen between steps. On completion the spinner becomes a check mark and the bar turns green.

Only the bar itself carries the stage accent (setup blue, ingest cyan, postpro magenta, export
yellow, green when finished); the percentage, timers and item label stay neutral or dim, so the
line reads as one object rather than a row of competing colours.

Everything degrades by console capability, because the target console is plain ``cmd.exe``:

* **Bar glyphs** — the block elements ``full block``, ``light shade`` and ``left half block``
  (used as a half-cell partial, so the bar advances in half steps rather than jumping a whole
  cell). All three are CP437 characters, so every console font Windows ships — Consolas,
  Lucida Console, the raster font — has them. Where the stdout encoding cannot represent them
  at all (a cp1252 pipe), the bar falls back to ASCII ``#`` and ``-``.
* **Spinner** — the braille dot spinner only where a modern terminal is positively identified
  (Windows Terminal, ConEmu, an embedded terminal that sets ``TERM_PROGRAM``, or any
  non-Windows console), because braille is absent from the fonts ``conhost`` uses and would
  render as empty boxes there. Plain ``cmd.exe`` gets the four CP437 half blocks rotating
  clockwise instead — still a smooth Unicode spinner, just one its fonts are guaranteed to
  have — and a console that cannot encode those falls back to ASCII. The completion mark
  needs the same positive signal (a check mark, else ASCII ``*``).
* **Colour** — ``rich`` resolves the style names to whatever the console supports, so the same
  accents work on a truecolor terminal and on an 8/16-colour ``cmd.exe``. ``NO_COLOR`` /
  ``FORCE_COLOR`` are honoured by ``rich`` itself.
* **Redraw rate** — lowered to ``legacy_refresh_per_second`` on a Windows console without
  virtual-terminal support, where ``rich`` must repaint through the win32 console API.

Off a terminal (output piped or redirected to a file, CI) ``rich`` skips the live redraw
entirely and emits one final line per stage when the bar closes, keeping saved logs tidy.

The display is gated by ``RuntimeOptions.progress_enabled``; when disabled,
:func:`stage_progress` yields an inert handle, so callers need no ``if enabled`` guards.
Progress is a pure console side effect: it never touches the data frames, so it cannot affect
determinism or the pipeline's output. It shares the one process-wide
:class:`~rich.console.Console` with the status-line helpers, so a warning printed mid-stage is
scrolled above the live bar instead of corrupting it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from rich.console import Console
from rich.progress import Progress as RichProgress
from rich.progress import (
    ProgressColumn,
    Task,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Column
from rich.text import Text

from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.console import get_console

# Bar glyphs. The block elements are CP437, so they render in every Windows console font;
# the ASCII pair is the fallback for a console encoding that cannot represent them.
_BLOCK_GLYPHS = ("█", "░", "▌")  # full block, light shade, left half block
_ASCII_GLYPHS = ("#", "-", "")
# Spinner frames, richest first. Braille reads best but is absent from the fonts conhost
# uses, so a console that can encode Unicode without being a known-modern terminal gets the
# four CP437 half blocks instead -- they rotate clockwise (left, top, right, bottom) and are
# guaranteed to render in Consolas and Lucida Console alike.
_BRAILLE_SPINNER: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_BLOCK_SPINNER: tuple[str, ...] = ("▌", "▀", "▐", "▄")
_ASCII_SPINNER: tuple[str, ...] = ("|", "/", "-", chr(92))
_UNICODE_DONE = "✓"  # check mark
_ASCII_DONE = "*"
# Environment variables that positively identify a terminal whose font covers braille.
_MODERN_TERMINAL_VARS = ("WT_SESSION", "WT_PROFILE_ID", "TERM_PROGRAM", "ConEmuANSI")


class _Glyphs(NamedTuple):
    """The glyph set chosen for the current console."""

    fill: str
    track: str
    partial: str
    spinner: tuple[str, ...]
    done: str


def _encodable(text: str, encoding: str) -> bool:
    """Whether ``encoding`` can represent every character in ``text``."""
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _is_modern_terminal() -> bool:
    """Whether the terminal is known to use a font with braille coverage.

    Every non-Windows console qualifies. On Windows only a positive signal does: the fonts
    ``conhost`` offers (Consolas, Lucida Console) have no braille block, so plain ``cmd.exe``
    must not be given a braille spinner even though it can encode one.
    """
    if sys.platform != "win32":
        return True
    return any(os.environ.get(name) for name in _MODERN_TERMINAL_VARS)


def _resolve_glyphs(console: Console) -> _Glyphs:
    """Pick the richest glyph set the console can both encode and render.

    Encodability and *renderability* are separate questions on Windows: a real ``cmd.exe``
    console encodes UTF-8 fine, yet its fonts have no braille block and no check mark. So the
    block glyphs are gated on encoding alone, while braille and the check mark additionally
    need a positively identified modern terminal.
    """
    encoding = getattr(console.file, "encoding", None) or "ascii"
    unicode_ok = _encodable("".join(_BLOCK_GLYPHS) + "".join(_BLOCK_SPINNER), encoding)
    modern = _is_modern_terminal()
    if not unicode_ok:
        fill, track, partial = _ASCII_GLYPHS
        spinner = _ASCII_SPINNER
    else:
        fill, track, partial = _BLOCK_GLYPHS
        spinner = (
            _BRAILLE_SPINNER
            if modern and _encodable("".join(_BRAILLE_SPINNER), encoding)
            else _BLOCK_SPINNER
        )
    done = _UNICODE_DONE if modern and _encodable(_UNICODE_DONE, encoding) else _ASCII_DONE
    return _Glyphs(fill=fill, track=track, partial=partial, spinner=spinner, done=done)


class _StageSpinnerColumn(ProgressColumn):
    """The leading spinner: a frame per tick in the stage accent, a done mark when finished.

    Drawn here rather than with :class:`rich.progress.SpinnerColumn` so the frame set can be
    chosen per console (see :func:`_resolve_glyphs`) without registering a custom spinner in
    ``rich``'s global registry. The frame index comes from the task's own clock, so it keeps
    turning on every repaint while a single step is busy.
    """

    def __init__(
        self, frames: tuple[str, ...], done: str, accent: str, finished_style: str, interval: float
    ) -> None:
        """Bind the column to a frame set, a done mark, the stage styles, and a frame interval."""
        super().__init__()
        self._frames = frames
        self._done = done
        self._accent = accent
        self._finished_style = finished_style
        self._interval = interval

    def render(self, task: Task) -> Text:
        """Render the current spinner frame, or the done mark on a finished task."""
        if task.finished:
            return Text(self._done, style=self._finished_style)
        index = int(task.get_time() / self._interval) % len(self._frames)
        return Text(self._frames[index], style=self._accent)


class _StageBarColumn(ProgressColumn):
    """The bar itself: a fixed-width block-glyph bar in the stage accent.

    Drawn here rather than with :class:`rich.progress.BarColumn` so the glyphs stay CP437 —
    ``BarColumn`` switches to a spaced ASCII bar on a legacy Windows console and to heavy
    box-drawing characters elsewhere, neither of which is guaranteed to render in ``cmd.exe``.
    The last cell shows a half-block when the fill lands mid-cell, so a long stage advances in
    half steps instead of jumping a whole cell at a time.
    """

    def __init__(
        self,
        glyphs: _Glyphs,
        width: int,
        accent: str,
        finished_style: str,
        track_style: str,
    ) -> None:
        """Bind the column to a glyph set, a width, and the stage's styles."""
        super().__init__()
        self._glyphs = glyphs
        self._width = width
        self._accent = accent
        self._finished_style = finished_style
        self._track_style = track_style

    def render(self, task: Task) -> Text:
        """Render ``task``'s completion as the bar."""
        total = task.total or 0
        if task.finished:
            fraction = 1.0
        elif total:
            fraction = min(1.0, task.completed / total)
        else:
            fraction = 0.0
        exact = fraction * self._width
        filled = min(int(exact), self._width)
        bar = self._glyphs.fill * filled
        if self._glyphs.partial and filled < self._width and exact - filled >= 0.5:
            bar += self._glyphs.partial
        style = self._finished_style if task.finished else self._accent
        text = Text(bar, style=style)
        text.append(self._glyphs.track * (self._width - len(bar)), style=self._track_style)
        return text


def _column_widths(console: Console) -> tuple[int, int]:
    """Return ``(bar_width, item_width)`` for ``console``, so the line never wraps.

    Both columns are fixed-width -- a reflowing line would break the in-place redraw -- and
    both are bounded, so a very wide console gets a tidy bar rather than one sprawling across
    the whole window. When the console is too narrow for both at full size the item column is
    squeezed to its minimum first and the bar gives way only after that, because a clipped
    workbook name still reads while a clipped bar is just wrong.
    """
    constants = get_pipeline_constants().progress
    available = console.width - constants.fixed_column_width - constants.label_width
    item = max(
        constants.item_min_width, min(constants.item_max_width, available - constants.bar_width)
    )
    bar = max(constants.bar_min_width, min(constants.bar_width, available - item))
    return bar, item


def _build_progress(label: str, console: Console) -> RichProgress:
    """Build the live display for one stage, styled and sized for ``console``."""
    constants = get_pipeline_constants().progress
    glyphs = _resolve_glyphs(console)
    bar_width, item_width = _column_widths(console)
    accent = constants.stage_styles.get(label, constants.default_stage_style)
    # rich reports legacy_windows on a console without virtual-terminal support, where every
    # repaint goes through the win32 API; refresh slower there to keep it flicker-free.
    rate = constants.refresh_per_second
    if console.legacy_windows:
        rate = constants.legacy_refresh_per_second
    return RichProgress(
        _StageSpinnerColumn(
            frames=glyphs.spinner,
            done=glyphs.done,
            accent=accent,
            finished_style=constants.finished_style,
            interval=constants.spinner_interval,
        ),
        TextColumn(
            "{task.description}",
            style=f"bold {accent}",
            table_column=Column(width=constants.label_width, no_wrap=True),
        ),
        _StageBarColumn(
            glyphs=glyphs,
            width=bar_width,
            accent=accent,
            finished_style=constants.finished_style,
            track_style=constants.track_style,
        ),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn(
            "{task.fields[item]}",
            style=constants.track_style,
            table_column=Column(width=item_width, no_wrap=True, overflow="ellipsis"),
        ),
        console=console,
        refresh_per_second=rate,
        transient=False,
    )


class StageProgress:
    """A single stage's progress handle over a live display (or nothing, when disabled).

    ``step`` advances the bar; ``pulse`` only updates the item label. Both are no-ops when
    disabled, so callers need no ``if enabled`` guards. ``step`` is also passed directly as the
    ingest reader's per-file callback, so each file nudges the bar forward.
    """

    __slots__ = ("_progress", "_task")

    def __init__(self, progress: RichProgress | None, task: TaskID | None = None) -> None:
        """Bind the handle to a live display and its task, or to ``None`` when disabled."""
        self._progress = progress
        self._task = task

    def step(self, message: str = "") -> None:
        """Advance the bar by one unit, recording the current item."""
        if self._progress is not None and self._task is not None:
            self._progress.update(self._task, advance=1, item=message)

    def pulse(self, message: str = "") -> None:
        """Update the current item without advancing."""
        if self._progress is not None and self._task is not None:
            self._progress.update(self._task, item=message)


@contextmanager
def stage_progress(label: str, total: int, *, enabled: bool) -> Iterator[StageProgress]:
    """Yield a :class:`StageProgress` for a stage of ``total`` advance units.

    Args:
        label: The stage label shown on the bar (e.g. ``"ingest"``); it selects the accent.
        total: The number of ``step`` advances the stage will make (100% when all are made).
        enabled: When ``False``, no bar is drawn and the handle is inert.

    Yields:
        The :class:`StageProgress` handle for the stage.
    """
    if not enabled:
        yield StageProgress(None)
        return
    bar_total = max(1, total)
    progress = _build_progress(label, get_console())
    with progress:
        task = progress.add_task(label, total=bar_total, item="")
        try:
            yield StageProgress(progress, task)
        finally:
            # Snap to 100% so the bar always closes full and green, even when the stage made
            # fewer advances than it declared.
            progress.update(task, completed=bar_total, item="")
            progress.refresh()
