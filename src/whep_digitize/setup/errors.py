"""Pipeline exception hierarchy — the Python equivalent of the R ``cli::cli_abort`` calls.

The R pipeline signals fatal conditions with ``cli_abort`` and non-fatal ones with
``cli_warn``. In Python, fatal conditions raise a :class:`WhepError` subclass and
non-fatal ones use the :mod:`warnings` module (or ``rich`` logging at call sites).
"""

from __future__ import annotations


class WhepError(Exception):
    """Base class for all pipeline errors."""


class ConfigurationError(WhepError):
    """Raised when configuration or constants are invalid or inconsistent."""


class ValidationError(WhepError):
    """Raised when a contract, schema, or input-validation check fails.

    This is the Python analogue of a failed ``checkmate`` assertion routed through
    ``assert_or_abort`` / ``abort_on_checkmate_failure``.
    """


class ContractError(WhepError):
    """Raised when a stage output violates its documented cross-stage contract."""
