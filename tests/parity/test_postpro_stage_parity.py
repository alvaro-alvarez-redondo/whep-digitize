"""Stage-level parity: ``run_postpro_pipeline`` output must match R over the frozen corpus.

Runs the full post-processing stage over the frozen import frame (``postpro_stage_input.json``,
the verified ``import_stage`` output) with the committed postpro-stage rule fixtures, and asserts
every column of the clean / normalize / harmonize frames plus the clean & harmonize multi-pass
diagnostics (``stop_reason`` / ``passes_executed`` / ``converged`` / ``matched_count``) all equal
R's ``run_postpro_pipeline_batch`` output. The ``value`` column is numeric (audit-parsed, then
prefix-folded by standardize), so it is compared through :func:`format_double_r` — R's
``as.character`` rendering. Both clean and harmonize converge in two passes (clean rewrites
``milk``'s unit; harmonize rewrites ``date``'s post-standardize unit).

Goldens are committed, so this runs on any checkout — CI included. A missing one still skips here;
``test_goldens_present.py`` is what makes that a hard failure.
"""

from __future__ import annotations

import dataclasses
import json

import polars as pl
import pytest
from goldens import FIXTURES_DIR, GOLDENS
from polars.testing import assert_series_equal

from whep_digitize.contracts import PostproResult
from whep_digitize.postpro.runner import run_postpro_pipeline
from whep_digitize.setup.config import load_pipeline_config
from whep_digitize.setup.helpers.numeric import format_double_r

_SPEC = GOLDENS["postpro_stage"]
_LAYERS = ("clean", "normalize", "harmonize")
# Every layer column except the numeric ``value`` (compared separately through format_double_r).
_STRING_COLUMNS = (
    "hemisphere",
    "continent",
    "polity",
    "commodity",
    "variable",
    "unit",
    "year",
    "notes",
    "footnotes",
    "yearbook",
    "document",
)


def _gold(name: str) -> list[str | None]:
    path = _SPEC.golden_paths()[name]
    if not path.is_file():
        pytest.skip(
            f"Golden {path} missing; regenerate with "
            f"`python tests/parity/capture.py {_SPEC.module}`"
        )
    data: list[str | None] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> PostproResult:
    """Run the postpro stage over the frozen import frame + committed stage rule fixtures."""
    assert _SPEC.fixture is not None
    columns = json.loads((FIXTURES_DIR / _SPEC.fixture).read_text(encoding="utf-8"))
    raw = pl.DataFrame(
        {name: pl.Series(name, values, dtype=pl.String) for name, values in columns.items()}
    )

    # Root the config at a writable temp dir (audit/standardize/template writes land there); point
    # the clean/harmonize rule dirs at the committed stage fixtures, exactly as the R golden does.
    base = load_pipeline_config(root=tmp_path_factory.mktemp("postpro_stage"))
    rule_root = FIXTURES_DIR / "rule_files_postpro"
    import_ = dataclasses.replace(
        base.paths.data.import_,
        cleaning=rule_root / "clean",
        harmonization=rule_root / "harmonize",
    )
    data_paths = dataclasses.replace(base.paths.data, import_=import_)
    config = dataclasses.replace(base, paths=dataclasses.replace(base.paths, data=data_paths))
    return run_postpro_pipeline(raw, config)


def _layer(result: PostproResult, layer: str) -> pl.DataFrame:
    frame = getattr(result, layer)
    assert isinstance(frame, pl.DataFrame)
    return frame


@pytest.mark.parity
@pytest.mark.parametrize("layer", _LAYERS)
def test_layer_columns_and_row_count(layer: str, result: PostproResult) -> None:
    frame = _layer(result, layer)
    assert frame.columns == _gold(f"{layer}_columns")
    assert str(frame.height) == _gold(f"{layer}_nrow")[0]


@pytest.mark.parity
@pytest.mark.parametrize("layer", _LAYERS)
@pytest.mark.parametrize("column", _STRING_COLUMNS)
def test_layer_string_column_matches_golden(layer: str, column: str, result: PostproResult) -> None:
    expected = pl.Series(column, _gold(f"{layer}_{column}"), dtype=pl.String)
    assert_series_equal(
        _layer(result, layer).get_column(column), expected, check_dtypes=True, check_names=True
    )


@pytest.mark.parity
@pytest.mark.parametrize("layer", _LAYERS)
def test_layer_value_column_matches_golden(layer: str, result: PostproResult) -> None:
    # value is a double (audit parse + standardize prefix-fold): render it R's as.character way.
    actual = [
        None if value is None else format_double_r(value)
        for value in _layer(result, layer).get_column("value").to_list()
    ]
    assert actual == _gold(f"{layer}_value")


@pytest.mark.parity
@pytest.mark.parametrize("layer", ("clean", "harmonize"))
def test_multi_pass_diagnostics_match_golden(layer: str, result: PostproResult) -> None:
    diagnostics = getattr(result.diagnostics, layer)
    multi_pass = diagnostics.multi_pass
    assert multi_pass is not None
    assert [multi_pass.stop_reason] == _gold(f"{layer}_stop_reason")
    assert [str(multi_pass.passes_executed)] == _gold(f"{layer}_passes")
    assert [str(multi_pass.converged).upper()] == _gold(f"{layer}_converged")
    assert [str(diagnostics.matched_count)] == _gold(f"{layer}_matched")
