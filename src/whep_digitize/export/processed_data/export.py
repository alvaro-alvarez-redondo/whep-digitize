r"""Processed-data TSV export (ports ``01`` / ``03`` / ``04`` of ``30-processed_data/``).

Writes the exportable layer tables (only ``harmonize`` by default) to
``{stem}.tsv`` via :meth:`polars.DataFrame.write_csv` with a tab separator. Two byte-parity
adjustments reproduce R ``data.table::fwrite(sep = "\t")`` exactly (verified against the R
4.6.0 install; see the parity test and ``.claude/docs/r-to-python-mapping.md``):

* **Line terminator.** ``fwrite`` uses the platform newline (``\r\n`` on Windows, ``\n`` on
  unix — ``.Platform$OS.type``); polars defaults to ``\n``. :data:`_FWRITE_EOL` mirrors
  ``fwrite`` so the golden (captured from R on this platform) and the port agree, on every
  platform, without hard-coding either newline.
* **Float formatting.** The exported ``value`` column is ``Float64`` (the audit stage parses
  it via ``readr::parse_double``). ``fwrite`` renders a double exactly like R
  ``as.character()`` under the pipeline's ``scipen = 999``: **15 significant figures, fixed
  notation, trailing zeros and a bare ``.0`` dropped** (``1.0`` -> ``1``, ``1000.0`` ->
  ``1000``). polars' shortest-round-trip formatter instead keeps ``1.0`` and switches to
  ``1e16``-style scientific. :func:`~whep_digitize.setup.helpers.numeric.format_double_r`
  reproduces the R rendering, so numeric
  columns are stringified before the write. For the finite decimals the pipeline actually
  produces (parsed inputs times exact unit factors) this is byte-identical to ``fwrite``; the
  two can only diverge in the 15th digit for *arbitrary* >=16-significant-figure doubles, which
  the pipeline never generates.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

import polars as pl

from whep_digitize.export.processed_data.layers import collect_layer_tables_for_export
from whep_digitize.setup.config import Config
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.numeric import format_double_r
from whep_digitize.setup.helpers.strings import normalize_filename

# ``data.table::fwrite`` eol default: "\r\n" on Windows, "\n" on unix (``.Platform$OS.type``).
_FWRITE_EOL: str = "\r\n" if os.name == "nt" else "\n"


def build_processed_export_path(config: Config, object_name: str) -> Path:
    """Resolve the processed-export ``.tsv`` path for an object.

    Ports R ``build_processed_export_path``. The directory itself is **not** created here;
    the caller (the export runner) is responsible for it, as in R.

    Args:
        config: The resolved pipeline configuration.
        object_name: The object name whose file stem is derived via
            :func:`~whep_digitize.setup.helpers.strings.normalize_filename`.

    Returns:
        ``<config.paths.data.export.processed>/<normalized_name>.tsv``.

    Raises:
        ValidationError: If ``object_name`` is empty.
    """
    if not object_name:
        raise ValidationError("object_name must be a non-empty string")
    suffix = config.export_config.processed_suffix
    stem = normalize_filename(object_name)
    return config.paths.data.export.processed / f"{stem}{suffix}"


def write_processed_table(
    frame: pl.DataFrame, output_path: Path, *, overwrite: bool = True
) -> Path:
    """Write one frame to a tab-separated ``.tsv`` file, byte-for-byte like R ``fwrite``.

    Ports R ``write_processed_table_fast``. Float columns are rendered with the R
    ``as.character`` / ``fwrite`` convention and the platform newline is matched (see module
    docstring). The parent directory must already exist.

    Args:
        frame: The table to write.
        output_path: Destination ``.tsv`` path.
        overwrite: When ``False`` and ``output_path`` exists, refuse to overwrite.

    Returns:
        ``output_path``.

    Raises:
        ValidationError: If ``overwrite`` is ``False`` and the file already exists.
    """
    if not overwrite and output_path.exists():
        raise ValidationError(f"file already exists and overwrite is disabled: {output_path}")
    _format_float_columns(frame).write_csv(output_path, separator="\t", line_terminator=_FWRITE_EOL)
    return output_path


def export_processed_data(
    config: Config,
    data_objects: Mapping[str, pl.DataFrame],
    *,
    overwrite: bool = True,
) -> dict[str, Path]:
    """Export the configured layer tables to processed-data TSVs.

    Ports R ``export_processed_data``. Detects all layer tables for traceability, keeps only
    those whose name ends in a configured export layer (``config.export_config.export_layers``,
    default ``("harmonize",)``), and writes each via :func:`write_processed_table`. The output
    directory must already exist (created by the export runner, as in R).

    Args:
        config: The resolved pipeline configuration.
        data_objects: Mapping of object name to frame (e.g. the postpro layer frames).
        overwrite: Passed through to :func:`write_processed_table`.

    Returns:
        Mapping of exported object name to its written ``.tsv`` path.

    Raises:
        ValidationError: If no layer tables are detected, or none match the export layers.
    """
    layer_tables = collect_layer_tables_for_export(data_objects)
    export_layers = config.export_config.export_layers or ("harmonize",)
    export_pattern = re.compile(
        r"_(" + "|".join(re.escape(layer) for layer in export_layers) + r")$"
    )
    export_tables = {
        name: frame for name, frame in layer_tables.items() if export_pattern.search(name)
    }

    if not export_tables:
        raise ValidationError(
            "no exportable layer tables found: detected layers "
            f"{tuple(layer_tables)}, but export_layers is {tuple(export_layers)}"
        )

    return {
        name: write_processed_table(
            frame, build_processed_export_path(config, name), overwrite=overwrite
        )
        for name, frame in export_tables.items()
    }


def _format_float_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Return ``frame`` with every float column rendered as R-``fwrite``-style strings.

    Non-float columns (string, integer) are left untouched — polars already writes them like
    ``fwrite``.
    """
    float_columns = [name for name, dtype in frame.schema.items() if dtype.is_float()]
    if not float_columns:
        return frame
    return frame.with_columns(
        [_format_float_series(frame[name]).alias(name) for name in float_columns]
    )


def _format_float_series(series: pl.Series) -> pl.Series:
    """Render a float :class:`polars.Series` as strings via the cardinality fast path.

    Distinct values are formatted once and mapped back (the idiom used by
    ``helpers.strings.normalize_string``); nulls are preserved as nulls (``fwrite`` writes
    ``NA`` as an empty field, which is exactly how :meth:`polars.DataFrame.write_csv` renders
    a null string).
    """
    uniques = series.drop_nulls().unique().to_list()
    if not uniques:
        return series.cast(pl.String)
    mapping = {value: format_double_r(value) for value in uniques}
    return series.replace_strict(mapping, default=None, return_dtype=pl.String)
