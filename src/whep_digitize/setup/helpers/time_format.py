"""Elapsed-time formatting.

Formats a duration in seconds as ``Ns`` / ``Nm Ns`` / ``Nh Nm`` for console output.
"""

from __future__ import annotations

from whep_digitize.setup.constants import get_pipeline_constants


def format_elapsed_time(seconds: float) -> str:
    """Format a duration for user-facing messages.

    Args:
        seconds: Elapsed seconds.

    Returns:
        ``"<N>s"`` below a minute, ``"<M>m <S>s"`` below an hour, else ``"<H>h <M>m"``.
    """
    time_units = get_pipeline_constants().time_units
    total = round(seconds)
    if total < time_units.seconds_per_minute:
        return f"{total}s"
    if total < time_units.seconds_per_hour:
        minutes, remainder = divmod(total, time_units.seconds_per_minute)
        return f"{minutes}m {remainder}s"
    hours, remainder = divmod(total, time_units.seconds_per_hour)
    minutes = remainder // time_units.seconds_per_minute
    return f"{hours}h {minutes}m"
