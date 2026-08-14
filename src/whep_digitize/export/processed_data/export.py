r"""Processed-data TSV export.

Writes the exportable layer tables — every layer by default: ``raw``, ``clean``, ``normalize``,
``harmonize`` — to ``{stem}.tsv`` via :meth:`polars.DataFrame.write_csv` with a tab separator.
The byte-level output contract (the export tests pin the first two bullets):

* **Record separator.** The platform newline — ``\r\n`` on Windows, ``\n`` elsewhere — resolved
  once into :data:`_FWRITE_EOL`; polars would otherwise always write ``\n``. Resolving it at
  runtime keeps the output correct on every platform without hard-coding either newline.
* **Float formatting.** The exported ``value`` column is ``Float64``, and doubles are rendered at
  **15 significant figures, fixed (never scientific) notation, trailing zeros and a bare trailing
  ``.`` removed** (``1.0`` -> ``1``, ``1000.0`` -> ``1000``, ``1e16`` -> ``10000000000000000``).
  polars' shortest-round-trip formatter instead keeps ``1.0`` and switches to ``1e16``-style
  scientific notation, so float columns are stringified with
  :func:`~whep_digitize.setup.helpers.numeric.format_double_fixed` before the write. For the finite
  decimals the pipeline actually produces (parsed inputs times exact unit factors) the rendering
  is exact; only *arbitrary* doubles carrying >=16 significant figures, which the pipeline never
  generates, could differ in the 15th digit.
* **Quoting and missing values.** A field is quoted only when it has to be — when it embeds a
  tab, a newline, or a double quote (which is then doubled). An empty string is written as ``""``
  while a null is written as a completely empty field, so the two stay distinguishable on
  re-read. Output is UTF-8.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

import polars as pl

from whep_digitize.export.processed_data.layers import collect_layer_tables_for_export
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.errors import ValidationError
from whep_digitize.setup.helpers.numeric import format_double_fixed
from whep_digitize.setup.helpers.strings import normalize_filename

# Record separator: the platform newline — "\r\n" on Windows, "\n" elsewhere.
_FWRITE_EOL: str = "\r\n" if os.name == "nt" else "\n"
# Fallback for an explicitly-emptied config: the configured default is every layer.
_DEFAULT_EXPORT_LAYERS = get_pipeline_constants().export_config.export_layers


def build_processed_export_path(config: Config, object_name: str) -> Path:
    """Resolve the processed-export ``.tsv`` path for an object.

    The directory itself is **not** created here; the caller (the export runner) is responsible
    for it.

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
    """Write one frame to a tab-separated ``.tsv`` file under the fixed byte-level contract.

    Float columns are stringified with the pipeline's fixed-notation double rendering and the
    record separator is the platform newline (see the module docstring). The parent directory
    must already exist.

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

    Detects all layer tables for traceability, keeps those whose name ends in a configured export
    layer (``config.export_config.export_layers``, which by default is every layer: ``raw``,
    ``clean``, ``normalize``, ``harmonize``), and writes each via
    :func:`write_processed_table`. A configured layer with no corresponding table is simply not
    written -- ``raw`` is absent unless the import frame was supplied to the export runner. The
    output directory must already exist (the export runner creates it).

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
    export_layers = config.export_config.export_layers or _DEFAULT_EXPORT_LAYERS
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
    """Return ``frame`` with every float column rendered as contract-conformant strings.

    Non-float columns (string, integer) are left untouched — polars already writes them exactly
    as the output contract requires.
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
    ``helpers.strings.normalize_string``); nulls stay null, which
    :meth:`polars.DataFrame.write_csv` renders as an empty field — the contract's missing-value
    form.
    """
    uniques = series.drop_nulls().unique().to_list()
    if not uniques:
        return series.cast(pl.String)
    mapping = {value: format_double_fixed(value) for value in uniques}
    return series.replace_strict(mapping, default=None, return_dtype=pl.String)
