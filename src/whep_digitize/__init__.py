"""whep-digitize — the WHEP digitization pipeline.

A deterministic, four-stage pipeline that processes WHEP source workbooks:

    setup (stage 0)  ->  ingest (stage 1)  ->  postpro (stage 2)  ->  export (stage 3)

The public entry point is :func:`whep_digitize.pipeline.run_pipeline`.

Stage-to-package mapping:

============================  ============================
Subpackage                    Responsibility
============================  ============================
:mod:`whep_digitize.setup`    constants, config, helpers
:mod:`whep_digitize.ingest`   discover, read, transform
:mod:`whep_digitize.postpro`  audit, clean, standardize
:mod:`whep_digitize.export`   processed TSV + unique lists
============================  ============================

``import`` is a Python keyword, so stage 1 is named ``ingest``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
