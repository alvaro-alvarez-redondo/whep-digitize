"""Workbook discovery — the Python port of ``10-discovery.R``.

Recursively scans an import folder for ``.xlsx`` workbooks and returns the file-metadata
frame produced by :func:`~whep_digitize.ingest.file_io.metadata.extract_file_metadata`.
When the folder holds no workbooks it warns and returns an empty metadata frame.

Two parity-relevant behaviours are reproduced from R ``fs::dir_ls``:

* **Path form** — paths are emitted with forward slashes (``Path.as_posix``), prefixed by
  ``import_folder`` exactly as passed (relative stays relative), matching ``fs``.
* **Ordering** — results are sorted by their full path string (Unicode code point). This
  matches ``fs::dir_ls``'s C-locale/radix ordering for the ASCII paths the pipeline
  produces and is deterministic regardless of filesystem enumeration order (parity risk
  #7 in ``.claude/docs/r-to-python-mapping.md``).

R source: ``r/1-import_pipeline/10-file_io/10-discovery.R``
(``discover_files``, ``discover_pipeline_files``).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import polars as pl

from whep_digitize.ingest.file_io.metadata import build_empty_file_metadata, extract_file_metadata
from whep_digitize.setup.config import Config
from whep_digitize.setup.helpers.assertions import require

_XLSX_SUFFIX = ".xlsx"


def discover_files(import_folder: Path | str) -> pl.DataFrame:
    """Discover ``.xlsx`` workbooks under an import folder.

    Args:
        import_folder: Directory to scan recursively. Accepted as a string or
            :class:`~pathlib.Path`; the emitted ``file_path`` values mirror its form.

    Returns:
        The file-metadata frame from :func:`extract_file_metadata`, one row per workbook
        in sorted path order, or an empty frame (with a warning) when none are found.

    Raises:
        ValidationError: If ``import_folder`` is blank or is not an existing directory
            (R ``checkmate`` ``check_string`` + ``check_directory_exists``).
    """
    raw_folder = str(import_folder)
    require(len(raw_folder) >= 1, "import_folder must be a non-empty path")
    folder = Path(import_folder)
    require(
        folder.is_dir(),
        f"import folder does not exist or is not a directory: {raw_folder}",
    )

    file_paths = sorted(
        entry.as_posix()
        for entry in folder.rglob(f"*{_XLSX_SUFFIX}")
        if entry.is_file() and entry.name.endswith(_XLSX_SUFFIX)
    )

    if not file_paths:
        warnings.warn(
            f"no xlsx files were found in the import folder (folder: {raw_folder})",
            stacklevel=2,
        )
        return build_empty_file_metadata()

    return extract_file_metadata(file_paths)


def discover_pipeline_files(config: Config) -> pl.DataFrame:
    """Resolve the raw import folder from ``config`` and discover its workbooks.

    Args:
        config: The resolved pipeline configuration; the raw import folder is
            ``config.paths.data.import_.raw``.

    Returns:
        The file-metadata frame from :func:`discover_files`.
    """
    return discover_files(config.paths.data.import_.raw)
