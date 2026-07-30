"""whep-digitize — Python/Polars port of the WHEP digitization pipeline.

A deterministic, four-stage pipeline that processes WHEP source workbooks:

    setup (stage 0)  ->  ingest (stage 1)  ->  postpro (stage 2)  ->  export (stage 3)

This package is the Python migration of the R project ``whep-digitalization``.
The public entry point is :func:`whep_digitize.pipeline.run_pipeline`.

Stage-to-package mapping (R -> Python):

======================  ===========================  ============================
R stage directory       Python subpackage            Responsibility
======================  ===========================  ============================
``0-general_pipeline``  :mod:`whep_digitize.setup`    constants, config, helpers
``1-import_pipeline``   :mod:`whep_digitize.ingest`   discover, read, transform
``2-postpro_pipeline``  :mod:`whep_digitize.postpro`  audit, clean, standardize
``3-export_pipeline``   :mod:`whep_digitize.export`   processed TSV + unique lists
======================  ===========================  ============================

``import`` is a Python keyword, so stage 1 is named ``ingest``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
