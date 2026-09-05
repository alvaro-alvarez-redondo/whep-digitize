"""Guard assertions — cheap inline precondition checks.

Lightweight runtime guards that raise :class:`~whep_digitize.setup.errors.ValidationError`
on failure, for conditions worth checking at every call. Heavier schema validation uses
``pydantic`` at stage boundaries.
"""

from __future__ import annotations

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


