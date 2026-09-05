r"""Postpro / audit.

Validates the consolidated dataset and parses ``value`` to numeric. Two deliberate behaviors:
invalid rows are **kept** in the audited output, and the audit regex ``^[0-9]+(\.[0-9]+)?$`` is
stricter than the float parser (``-3.5`` is flagged yet parses to ``-3.5``).

Modules:

* ``config.py`` — audit-config validation, empty findings schema, audit-root prep.
* ``validation.py`` — non-empty + numeric-string validators, validation plan, master validation
  registry, audit-column resolution.
* ``audit.py`` — ``audit_dataset``: run validations, then parse ``value`` to Float64
  (``cast(Float64, strict=False)``).
"""

from __future__ import annotations
