"""Guard assertions — the Python port of ``02-assertions.R`` (``assert_or_abort``).

Lightweight runtime guards that raise :class:`~whep_digitize.setup.errors.ValidationError`
on failure, the Python analogue of routing a failed ``checkmate`` result through
``cli::cli_abort``. Heavier schema validation uses ``pydantic`` at stage boundaries.
"""

from __future__ import annotations

from collections.abc import Iterable

from whep_digitize.setup.errors import ValidationError


def require(condition: bool, message: str) -> None:
    """Raise :class:`ValidationError` with ``message`` unless ``condition`` holds.

    Args:
        condition: The condition that must be true.
        message: Error message when the condition fails.

    Raises:
        ValidationError: If ``condition`` is falsy.
    """
    if not condition:
        raise ValidationError(message)


def require_columns(present: Iterable[str], required: Iterable[str], *, context: str) -> None:
    """Assert that every required column is present.

    Args:
        present: Column names available.
        required: Column names that must be present.
        context: Human-readable context for the error message.

    Raises:
        ValidationError: If any required column is missing.
    """
    present_set = set(present)
    missing = [column for column in required if column not in present_set]
    if missing:
        raise ValidationError(f"{context}: missing required column(s): {missing}")
