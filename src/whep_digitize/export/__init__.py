"""Stage 3 — export.

Writes processed-data TSVs (only the ``harmonize`` layer by default) and per-column
unique-value list workbooks. Public entry point:
:func:`whep_digitize.export.runner.run_export_pipeline` -> :class:`OutputResult`.

Sub-packages:

* :mod:`~whep_digitize.export.processed_data` — layer detection + TSV writing
* :mod:`~whep_digitize.export.lists` — per-column unique-list xlsx with layer merging
"""

from __future__ import annotations
