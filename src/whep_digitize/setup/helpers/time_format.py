"""Elapsed-time formatting.

Formats a duration in seconds as ``H:MM:SS`` for console output -- the same rendering the
stage progress bars use, so the completion line and the bars read as one clock.
"""

from __future__ import annotations

from datetime import timedelta


def format_elapsed_time(seconds: float) -> str:
    """Format a duration for user-facing messages.

    Deliberately identical to :class:`rich.progress.TimeElapsedColumn`, down to using
    :class:`datetime.timedelta`'s own string form: the stage bars render their elapsed clock
    that way, and the completion line must match them exactly.

    Args:
        seconds: Elapsed seconds. Negative values are clamped to zero.

    Returns:
        ``"H:MM:SS"`` (e.g. ``"0:02:27"``), seconds truncated to a whole number.
    """
    return str(timedelta(seconds=max(0, int(seconds))))
