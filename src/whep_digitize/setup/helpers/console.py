"""Console messaging — the Python port of the console helpers in ``02-progress.R``.

Palette-matched status lines (``pipeline_alert_info`` / ``pipeline_alert_success`` etc.)
built on :mod:`rich`. Progress bars themselves are handled by ``rich.progress`` at the
stage runners (Phase 5 of the roadmap).
"""

from __future__ import annotations

from rich.console import Console

_console = Console()


def get_console() -> Console:
    """Return the shared :class:`rich.console.Console`."""
    return _console


# ASCII-only status markers. Unicode glyphs (e.g. a check mark) crash rich's legacy
# Windows renderer when stdout is a cp1252 console, so the markers stay in the ASCII
# range to guarantee the pipeline never fails on output encoding, on any platform.
def alert_info(message: str) -> None:
    """Print an informational line (R ``pipeline_alert_info``)."""
    _console.print(f"[cyan]i[/cyan] {message}")


def alert_success(message: str) -> None:
    """Print a success line (R ``pipeline_alert_success``)."""
    _console.print(f"[bold green]OK[/bold green] {message}")


def alert_warning(message: str) -> None:
    """Print a warning line."""
    _console.print(f"[yellow]![/yellow] {message}")


def alert_error(message: str) -> None:
    """Print an error line."""
    _console.print(f"[bold red]x[/bold red] {message}")
