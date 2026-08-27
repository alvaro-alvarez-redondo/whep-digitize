r"""Stage progress bars — a self-drawn text bar with a live timer.

Each stage runner wraps its work in :func:`stage_progress`, a context manager that yields a
:class:`StageProgress`. ``step`` advances the bar by one unit; ``pulse`` updates the trailing
message without advancing. The long ingest read advances the bar once per file (``step`` is
its per-file callback), so the bar fills smoothly across the whole run.

The bar is drawn directly to ``stdout`` as text and overwritten in place with a carriage
return, so it renders inline in any console — a terminal, ``cmd.exe``, or a Jupyter-kernel
console like Positron's. On a *live* console (a TTY, or an IPython/Jupyter kernel whose stdout
overwrites on ``\r``) a background daemon thread redraws the line a few times a second, so an
**elapsed-time counter** ticks up, a **percentage** advances, and a spinner animates in real
time even while a single step is busy (a slow workbook read); the bar therefore always looks
alive, never frozen between steps. Where stdout is not a live console (output redirected to a
file, CI), no thread is started and the line is redrawn only when a block fills, keeping piped
logs tidy.

Everything degrades by capability so it is safe on any console:

* **Glyphs** — Unicode block glyphs (``█ ▏..▉ ·  │``, with 1/8-block partials for smooth,
  sub-cell fill) and a braille spinner (``⠋⠙⠹…``) with a ``✓`` completion mark are used only
  where the stdout encoding can represent them; otherwise ASCII fallbacks (``#`` fill, ``-``
  track, ``|`` edges, ``|/-\`` spinner, ``*`` done).
* **Colour** — a bold, per-stage-coloured label, a running bar / spinner / percentage in the
  stage's hue (setup blue, ingest cyan, postpro magenta, export yellow), a green finished bar +
  ``✓``, and a dim ``running stage:`` prefix / empty track / timer, emitted only where ANSI is
  reliably interpreted: a Jupyter kernel, a non-Windows TTY, or a Windows console once
  virtual-terminal processing is enabled best-effort via ``SetConsoleMode`` (the ``colorama``
  trick; it silently no-ops on a console too old to support it, leaving the bar uncoloured but
  fully functional). A console that pipes stdout but advertises ANSI via ``$TERM`` (an embedded
  app / IDE terminal) is coloured automatically — redrawn per block, without the animation
  thread — unless stdout is a redirected file. ``FORCE_COLOR`` (any value but ``0``) forces the
  full live + colour experience anywhere; ``NO_COLOR`` (per no-color.org) forces colour off.

Every field is fixed-width, so the ``\r`` redraw always fully overwrites the previous frame.

The display is gated by ``RuntimeOptions.progress_enabled``; when disabled,
:func:`stage_progress` yields an inert handle. Progress is a pure console side effect: it never
touches the data frames, so it cannot affect determinism or the pipeline's output.
"""

from __future__ import annotations

import os
import stat
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

_BAR_WIDTH = 24
_LABEL_WIDTH = 12
_MESSAGE_WIDTH = 24
_ELAPSED_WIDTH = 7
_PERCENT_WIDTH = 4  # "  0%" .. "100%"
# How often the background thread redraws on a live console, in seconds (~8 fps: a smooth
# spinner and a tenth-of-a-second timer without flooding a kernel's iopub channel).
_TICK_SECONDS = 0.12
# Drawn on the bar line itself (kept by the carriage-return redraw) so the bar shares one line
# with the stage announcement. A spinner frame precedes it; the label is padded to _LABEL_WIDTH
# so bars line up vertically across stages.
_STAGE_WORD = "running stage: "

_ANSI_DIM = "\x1b[2m"
_ANSI_BOLD = "\x1b[1m"
_ANSI_RESET = "\x1b[0m"
_ANSI_GREEN = "\x1b[92m"  # bright green — the finished accent
# Per-stage running accent (bright 16-colour palette; unknown labels fall back to cyan).
_STAGE_COLORS = {
    "setup": "\x1b[94m",  # bright blue
    "ingest": "\x1b[96m",  # bright cyan
    "postpro": "\x1b[95m",  # bright magenta
    "export": "\x1b[93m",  # bright yellow
}
_DEFAULT_ACCENT = "\x1b[96m"  # bright cyan

# 1/8-block partial-fill glyphs, index 1..7 (index 0 = no partial). Left-to-right eighths.
_PARTIAL_BLOCKS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")


def _encodable(text: str) -> bool:
    """Whether the current stdout encoding can represent every character in ``text``."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _bar_glyphs() -> tuple[str, str, str, tuple[str, ...]]:
    """Return ``(fill, empty, edge, partials)`` glyphs the stdout encoding can represent.

    Prefers Unicode block characters (``█``, ``·``, ``│``) plus the 1/8-block partial-fill
    ramp for smooth sub-cell motion; falls back to ASCII (``#``, ``-``, ``|``, no partials) on
    a console (e.g. cp1252) that cannot encode them.
    """
    if _encodable("█·│" + "".join(_PARTIAL_BLOCKS)):
        return "█", "·", "│", _PARTIAL_BLOCKS
    return "#", "-", "|", ()


def _spinner_frames() -> tuple[str, ...]:
    r"""Return spinner frames the stdout encoding can represent (braille, else ASCII ``|/-\``)."""
    frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    if _encodable("".join(frames)):
        return frames
    return ("|", "/", "-", "\\")


def _done_glyph() -> str:
    """Return the completion mark (``✓`` where encodable, else ASCII ``*``)."""
    return "✓" if _encodable("✓") else "*"


def _is_jupyter_kernel() -> bool:
    """Whether we run under an IPython/Jupyter (ZMQ) kernel, e.g. Positron's Python console."""
    ipython = sys.modules.get("IPython")
    get_ipython = getattr(ipython, "get_ipython", None) if ipython is not None else None
    shell = get_ipython() if get_ipython is not None else None
    return shell is not None and type(shell).__name__ == "ZMQInteractiveShell"


@lru_cache(maxsize=1)
def _enable_windows_vt() -> bool:
    """Best-effort enable ANSI virtual-terminal processing on the Windows stdout console.

    Mirrors what ``colorama`` does: flip ``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` on the console
    mode so ANSI escapes render instead of printing as literal ``←[36m`` noise. Cached (the
    console mode is process-global) and fully defensive: returns ``False`` — leaving the bar
    uncoloured but working — on any failure (redirected stdout, a console too old to support
    VT, or a missing API).
    """
    if sys.platform != "win32":
        return True  # non-Windows TTYs interpret ANSI natively
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        std_output_handle = -11
        enable_vt = 0x0004
        handle = kernel32.GetStdHandle(std_output_handle)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except Exception:  # pragma: no cover - platform/API defensive
        return False


def _force_color() -> bool:
    """Whether ``FORCE_COLOR`` is set to a truthy value (any value but ``0`` / ``false``)."""
    force = os.environ.get("FORCE_COLOR")
    return force is not None and force.lower() not in ("0", "false")


def _term_supports_ansi() -> bool:
    """Whether ``$TERM`` advertises an ANSI-capable terminal (set, and not ``dumb``)."""
    term = os.environ.get("TERM", "")
    return bool(term) and term != "dumb"


def _stdout_is_regular_file() -> bool:
    """Whether stdout is a redirected regular file, where ANSI would pollute a saved log."""
    try:
        return stat.S_ISREG(os.fstat(sys.stdout.fileno()).st_mode)
    except (OSError, ValueError, AttributeError):
        return False


def _console_caps() -> tuple[bool, bool]:
    r"""Return ``(live, color)`` for the current stdout.

    ``live`` gates the in-place ``\r`` redraw with its animated spinner/timer; ``color`` gates
    ANSI styling. Resolution order:

    * ``NO_COLOR`` set (any value, per no-color.org) -> never colour (still animate on a TTY);
    * ``FORCE_COLOR`` set (any value but ``0`` / ``false``) -> force live + colour;
    * a Jupyter kernel, or a TTY whose console accepts VT (native on non-Windows; enabled
      best-effort on Windows) -> live + colour;
    * a console that pipes stdout yet advertises ANSI via ``$TERM`` and is not a redirected
      file (an embedded app / IDE terminal) -> colour, redrawn per block (no animation thread);
    * otherwise (a plain pipe, a redirected file, ``TERM=dumb``) -> a plain, uncoloured bar.
    """
    jupyter = _is_jupyter_kernel()
    isatty = getattr(sys.stdout, "isatty", None)
    tty = bool(callable(isatty) and isatty())
    if os.environ.get("NO_COLOR") is not None:
        return jupyter or tty, False
    if _force_color():
        _enable_windows_vt()  # best-effort; harmless if stdout is not a Windows console
        return True, True
    if jupyter or (tty and _enable_windows_vt()):
        return True, True
    if _term_supports_ansi() and not _stdout_is_regular_file():
        return False, True
    return jupyter or tty, False


def _format_elapsed(seconds: float) -> str:
    """Human elapsed time within :data:`_ELAPSED_WIDTH`: ``3.4s`` / ``12.3s`` / ``1m05s``."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class _TextBar:
    """A single stage's bar, drawn to ``stdout`` and overwritten in place.

    On a live console a daemon thread redraws it every :data:`_TICK_SECONDS` so the elapsed
    timer, percentage, and spinner animate between steps; otherwise it is redrawn only when a
    block fills. On :meth:`close` the bar snaps to 100%, turns green, and shows a ``✓``.
    """

    __slots__ = (
        "_accent",
        "_color",
        "_done",
        "_edge",
        "_empty",
        "_fill",
        "_finished",
        "_label",
        "_last_filled",
        "_live",
        "_lock",
        "_message",
        "_partials",
        "_spinner",
        "_spinner_idx",
        "_start",
        "_stop",
        "_ticker",
        "_total",
    )

    def __init__(self, label: str, total: int) -> None:
        self._label = label
        self._accent = _STAGE_COLORS.get(label, _DEFAULT_ACCENT)
        self._total = max(1, total)
        self._done = 0
        self._message = ""
        self._last_filled = -1
        self._finished = False
        self._fill, self._empty, self._edge, self._partials = _bar_glyphs()
        self._spinner = _spinner_frames()
        self._spinner_idx = 0
        self._start = time.monotonic()
        self._live, self._color = _console_caps()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ticker: threading.Thread | None = None
        with self._lock:
            self._render()
        if self._live:
            self._ticker = threading.Thread(target=self._animate, name="whep-progress", daemon=True)
            self._ticker.start()

    def advance(self, message: str) -> None:
        """Advance by one unit and record the current item."""
        with self._lock:
            self._done += 1
            self._message = message
            self._render()

    def describe(self, message: str) -> None:
        """Record the current item without advancing."""
        with self._lock:
            self._message = message
            self._render()

    def close(self) -> None:
        """Stop the animation and finalize the bar line so following output starts fresh."""
        self._stop.set()
        if self._ticker is not None:
            self._ticker.join(timeout=1.0)
        with self._lock:
            self._finished = True
            self._message = ""
            self._render(force=True)
            self._write("\n")

    def _animate(self) -> None:
        """Background loop: advance the spinner and refresh the timer until :meth:`close`."""
        while not self._stop.wait(_TICK_SECONDS):
            with self._lock:
                self._spinner_idx += 1
                self._render(force=True)

    def _fraction(self) -> float:
        """Completion in ``[0, 1]`` (100% once finished, regardless of step count)."""
        if self._finished:
            return 1.0
        return min(1.0, self._done / self._total)

    def _bar_body(self, fraction: float) -> tuple[str, int]:
        """Return ``(filled_glyphs, empty_count)`` for ``fraction``, using partials when live.

        On a live console with Unicode partials, the last cell shows a 1/8-block glyph for
        smooth sub-cell fill; elsewhere the bar fills in whole cells only.
        """
        exact = fraction * _BAR_WIDTH
        full = min(int(exact), _BAR_WIDTH)
        if self._live and self._partials and full < _BAR_WIDTH:
            eighths = int((exact - full) * 8)
            if eighths:
                return self._fill * full + self._partials[eighths], _BAR_WIDTH - full - 1
        return self._fill * full, _BAR_WIDTH - full

    def _render(self, *, force: bool = False) -> None:
        fraction = self._fraction()
        filled = min(int(fraction * _BAR_WIDTH), _BAR_WIDTH)
        # Off a live console (piped/CI) redraw only when a whole block fills, so logs stay tidy.
        if not force and not self._live and filled == self._last_filled:
            return
        self._last_filled = filled

        accent = _ANSI_GREEN if self._finished else self._accent
        if self._finished:
            glyph = _done_glyph()
        elif self._live:
            glyph = self._spinner[self._spinner_idx % len(self._spinner)]
        else:
            glyph = "*"
        filled_glyphs, empty_count = self._bar_body(fraction)
        empty_glyphs = self._empty * empty_count
        label = f"{self._label:<{_LABEL_WIDTH}}"
        percent = f"{int(fraction * 100):>{_PERCENT_WIDTH - 1}}%"
        elapsed = f"{_format_elapsed(time.monotonic() - self._start):>{_ELAPSED_WIDTH}}"
        message = f"{self._message:<{_MESSAGE_WIDTH}.{_MESSAGE_WIDTH}}"

        if self._color:
            frame = f"{_ANSI_BOLD}{accent}{glyph}{_ANSI_RESET}"
            stage_word = f"{_ANSI_DIM}{_STAGE_WORD}{_ANSI_RESET}"
            label = f"{_ANSI_BOLD}{accent}{label}{_ANSI_RESET}"
            edge = f"{_ANSI_BOLD}{accent}{self._edge}{_ANSI_RESET}"
            filled_part = f"{_ANSI_BOLD}{accent}{filled_glyphs}{_ANSI_RESET}"
            bar = f"{filled_part}{_ANSI_DIM}{empty_glyphs}{_ANSI_RESET}"
            percent = f"{_ANSI_BOLD}{accent}{percent}{_ANSI_RESET}"
            elapsed = f"{_ANSI_DIM}{elapsed}{_ANSI_RESET}"
        else:
            frame = glyph
            stage_word = _STAGE_WORD
            edge = self._edge
            bar = filled_glyphs + empty_glyphs
        line = f"\r{frame} {stage_word}{label} {edge}{bar}{edge} {percent} {elapsed}  {message}"
        self._write(line)

    def _write(self, text: str) -> None:
        stream = sys.stdout
        try:
            stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "ascii"
            stream.write(text.encode(encoding, "replace").decode(encoding))
        stream.flush()


class StageProgress:
    """A single stage's progress handle over a :class:`_TextBar` (or nothing, when disabled).

    ``step`` advances the bar; ``pulse`` only updates the message. Both are no-ops when
    disabled, so callers need no ``if enabled`` guards. ``step`` is also passed directly as the
    ingest reader's per-file callback, so each file nudges the bar forward.
    """

    __slots__ = ("_bar",)

    def __init__(self, bar: _TextBar | None) -> None:
        """Bind the handle to a bar, or to ``None`` when progress is disabled."""
        self._bar = bar

    def step(self, message: str = "") -> None:
        """Advance the bar by one unit."""
        if self._bar is not None:
            self._bar.advance(message)

    def pulse(self, message: str = "") -> None:
        """Update the message without advancing."""
        if self._bar is not None:
            self._bar.describe(message)


@contextmanager
def stage_progress(label: str, total: int, *, enabled: bool) -> Iterator[StageProgress]:
    """Yield a :class:`StageProgress` for a stage of ``total`` advance units.

    Args:
        label: The stage label shown on the bar (e.g. ``"ingest"``).
        total: The number of ``step`` advances the stage will make (100% when all are made).
        enabled: When ``False``, no bar is drawn and the handle is inert.

    Yields:
        The :class:`StageProgress` handle for the stage.
    """
    if not enabled:
        yield StageProgress(None)
        return
    bar = _TextBar(label, total)
    try:
        yield StageProgress(bar)
    finally:
        bar.close()
