"""Pipeline exception hierarchy.

Fatal conditions raise a :class:`WhepError` subclass; non-fatal ones are signalled through
the :mod:`warnings` module (or ``rich`` logging at call sites).
"""

from __future__ import annotations


class WhepError(Exception):
    """Base class for all pipeline errors."""


class ConfigurationError(WhepError):
    """Raised when configuration or constants are invalid or inconsistent."""


class ValidationError(WhepError):
    """Raised when a contract, schema, or input-validation check fails.

    Raised by the guard helpers in :mod:`whep_digitize.setup.helpers.assertions` and by the
    inline argument/schema checks the stages perform at their boundaries.
    """


class ContractError(WhepError):
    """Raised when a stage output violates its documented cross-stage contract."""
