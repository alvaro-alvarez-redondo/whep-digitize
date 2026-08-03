"""Ingest / file IO — workbook discovery and file-name metadata.

Modules:

* :mod:`~whep_digitize.ingest.file_io.discovery` — ``discover_files`` /
  ``discover_pipeline_files``: recursive ``*.xlsx`` scan -> file-metadata frame.
* :mod:`~whep_digitize.ingest.file_io.metadata` — ``extract_file_metadata`` /
  ``build_empty_file_metadata``: positional file-name token parsing (yearbook = token 2 +
  first 4-digit token; commodity = tokens 7+) and ASCII check, reusing
  :mod:`whep_digitize.setup.helpers.tokens`.
"""

from __future__ import annotations
