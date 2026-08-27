"""Filename token extraction.

Parses ``yearbook`` and ``commodity`` out of underscore-delimited source file names using
the WHEP positional convention. Used by the ingest stage's metadata extraction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from whep_digitize.setup.constants import get_pipeline_constants

_constants = get_pipeline_constants()
_YEAR_TOKEN_RE = re.compile(_constants.patterns.yearbook_token_4digit)
_EXTENSION_RE = re.compile(r"\.[^.]+$")


def extract_yearbook(parts: Sequence[str]) -> str | None:
    """Build the yearbook token from split filename parts.

    Yearbook = the first token joined to the first 4-digit (``YYYY``) token with an
    underscore. Requires at least two parts and a 4-digit token.

    Args:
        parts: Filename split on ``"_"``.

    Returns:
        The ``"<part1>_<year>"`` yearbook, or ``None`` if it cannot be formed.
    """
    if len(parts) < 2:
        return None
    year_token = next((part for part in parts if _YEAR_TOKEN_RE.match(part)), None)
    if year_token is None:
        return None
    return f"{parts[0]}_{year_token}"


def extract_commodity(parts: Sequence[str], start_index: int | None = None) -> str | None:
    """Build the commodity token from split filename parts.

    Commodity = tokens from ``start_index`` onward (1-based, default 7), with the file
    extension stripped from the last token, joined with ``"_"``. Returns ``None`` when
    there are too few parts.

    Args:
        parts: Filename split on ``"_"``.
        start_index: 1-based index of the first commodity token; defaults to the
            ``commodity_start_index`` constant.

    Returns:
        The commodity name, or ``None``.
    """
    index = start_index if start_index is not None else _constants.tokens.commodity_start_index
    if len(parts) < index:
        return None
    commodity_parts = list(parts[index - 1 :])
    commodity_parts[-1] = _EXTENSION_RE.sub("", commodity_parts[-1])
    return "_".join(commodity_parts)
