"""Ingest / file IO — ports ``r/1-import_pipeline/10-file_io/``.

Modules:

* :mod:`~whep_digitize.ingest.file_io.discovery` (``10-discovery.R``) — ``discover_files``
  / ``discover_pipeline_files``: recursive ``*.xlsx`` scan -> file-metadata frame.
* :mod:`~whep_digitize.ingest.file_io.metadata` (``10-metadata.R``) —
  ``extract_file_metadata`` / ``build_empty_file_metadata``: positional file-name token
  parsing (yearbook = token 2 + first 4-digit token; commodity = tokens 7+) and ASCII
  check, reusing :mod:`whep_digitize.setup.helpers.tokens`.
"""

from __future__ import annotations
