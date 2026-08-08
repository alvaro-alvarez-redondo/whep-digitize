r"""Postpro / audit.

Validates the consolidated dataset, exports a highlighted invalid-row workbook, and parses
``value`` to numeric. Two deliberate behaviors: invalid rows are **kept** in the audited output,
and the audit regex ``^[0-9]+(\.[0-9]+)?$`` is stricter than the float parser (``-3.5`` is
flagged yet parses to ``-3.5``).

Modules:

* ``config.py`` — audit-config validation, empty findings schema, audit-root prep, output-path
  resolution.
* ``validation.py`` — non-empty + numeric-string validators, validation plan, master validation
  registry, audit-column resolution.
* ``export.py`` — styled per-cell Excel highlight via openpyxl (``PatternFill`` + bold font +
  thick border; 1-based row/col + header offset).
* ``audit.py`` — ``audit_data_output``: run validations, export invalid rows, then parse
  ``value`` to Float64 (``cast(Float64, strict=False)``).
"""

from __future__ import annotations
