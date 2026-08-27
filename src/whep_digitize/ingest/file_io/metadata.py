"""File-name metadata extraction.

Parses the WHEP positional file-name convention into ``yearbook`` and ``commodity``
tokens, flags non-ASCII file names, and returns a typed metadata frame. The positional
parsing is delegated to :mod:`whep_digitize.setup.helpers.tokens` (``yearbook`` =
second token joined to the first 4-digit token; ``commodity`` = tokens 7 onward with the
extension stripped from the last one) so discovery and any future caller share one
convention.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

import polars as pl

from whep_digitize.setup.helpers.assertions import require
from whep_digitize.setup.helpers.tokens import extract_commodity, extract_yearbook

# Column order + dtypes shared by build_empty_file_metadata and extract_file_metadata so
# the two frames are identical in shape (five String columns plus the Boolean is_ascii).
# Declared as a schema so all-null token columns still land as String rather than being
# inferred as Null.
_METADATA_SCHEMA = pl.Schema(
    {
        "file_path": pl.String(),
        "file_name": pl.String(),
        "commodity": pl.String(),
        "yearbook": pl.String(),
        "is_ascii": pl.Boolean(),
        "error_message": pl.String(),
    }
)

_NON_ASCII_MESSAGE_PREFIX = "non-ascii file name detected: "


def build_empty_file_metadata() -> pl.DataFrame:
    """Return a zero-row file-metadata frame with the canonical schema.

    The empty-result counterpart of :func:`extract_file_metadata`, returned by
    :func:`~whep_digitize.ingest.file_io.discovery.discover_files` when an input folder
    holds no workbooks.

    Returns:
        An empty :class:`polars.DataFrame` with columns ``file_path``, ``file_name``,
        ``commodity``, ``yearbook``, ``is_ascii``, ``error_message``.
    """
    return pl.DataFrame(schema=_METADATA_SCHEMA)


def extract_file_metadata(file_paths: Sequence[str]) -> pl.DataFrame:
    """Parse file paths into a structured metadata frame.

    For each path the base file name is parsed positionally into ``yearbook`` and
    ``commodity`` (see :mod:`whep_digitize.setup.helpers.tokens`), checked for ASCII
    encoding, and — when non-ASCII — annotated with an ``error_message``. ``file_path`` is
    retained verbatim; tokens that cannot be formed are ``None``.

    Args:
        file_paths: One or more file paths (typically the forward-slash output of
            :func:`~whep_digitize.ingest.file_io.discovery.discover_files`).

    Returns:
        A :class:`polars.DataFrame` with the schema of :func:`build_empty_file_metadata`,
        one row per input path in input order.

    Raises:
        ValidationError: If ``file_paths`` is empty.
    """
    require(len(file_paths) >= 1, "file_paths must contain at least one path")

    file_names = [PurePosixPath(path).name for path in file_paths]
    yearbooks: list[str | None] = []
    commodities: list[str | None] = []
    for name in file_names:
        parts = name.split("_")
        yearbooks.append(extract_yearbook(parts))
        commodities.append(extract_commodity(parts))
    is_ascii_flags = [name.isascii() for name in file_names]
    error_messages = [
        None if ascii_ok else f"{_NON_ASCII_MESSAGE_PREFIX}{name}"
        for name, ascii_ok in zip(file_names, is_ascii_flags, strict=True)
    ]

    return pl.DataFrame(
        {
            "file_path": [str(path) for path in file_paths],
            "file_name": file_names,
            "commodity": commodities,
            "yearbook": yearbooks,
            "is_ascii": is_ascii_flags,
            "error_message": error_messages,
        },
        schema=_METADATA_SCHEMA,
    )
