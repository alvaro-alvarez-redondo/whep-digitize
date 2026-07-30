"""Parity test: the multi-pass clean/harmonize driver must match the R golden.

Exercises the port of ``22-layer-runner.R`` (``run_rule_stage_layer_batch``) + the payload
composition (``23-payload-application.R``) end-to-end over committed rule workbooks. For each of
the clean and harmonize stages it asserts the converged data columns, the ``stop_reason`` /
``passes_executed`` / ``converged`` multi-pass diagnostics, and the ``matched_count`` all match R.

Each stage rewrites ``unit`` on pass 1 and no-ops on pass 2, so it converges (``changed_value_count
== 0``) in two passes — the common convergence path. If a golden is absent (fresh checkout —
goldens are gitignored), the test skips.
"""

from __future__ import annotations

import dataclasses
import json

import polars as pl
import pytest
from r_harness import FIXTURES_DIR
from registry import CAPTURES

from whep_digitize.postpro.clean_harmonize.layer_runner import (
    StageLayerResult,
    run_cleaning_layer_batch,
    run_harmonize_layer_batch,
)
from whep_digitize.setup.config import Config

_SPEC = CAPTURES["layer_batch"]
_FIXTURE_NAME = _SPEC.fixture
assert _FIXTURE_NAME is not None
_FIXTURE_PATH = FIXTURES_DIR / _FIXTURE_NAME
_TIMESTAMP = "2026-01-01T00:00:00Z"


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
def dataset() -> pl.DataFrame:
    data: dict[str, list[str]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return pl.DataFrame(
        {key: pl.Series(key, values, dtype=pl.String) for key, values in data.items()}
    )


def _config_with_rule_dirs(config: Config) -> Config:
    import_ = dataclasses.replace(
        config.paths.data.import_,
        cleaning=FIXTURES_DIR / "rule_files" / "clean",
        harmonization=FIXTURES_DIR / "rule_files" / "harmonize",
    )
    data = dataclasses.replace(config.paths.data, import_=import_)
    return dataclasses.replace(config, paths=dataclasses.replace(config.paths, data=data))


def _assert_stage(result: StageLayerResult, prefix: str) -> None:
    assert result.data.columns == _gold(f"{prefix}_columns")
    assert result.data.get_column("commodity").to_list() == _gold(f"{prefix}_commodity")
    assert result.data.get_column("unit").to_list() == _gold(f"{prefix}_unit")
    assert result.data.get_column("value").to_list() == _gold(f"{prefix}_value")
    multi_pass = result.diagnostics.multi_pass
    assert multi_pass is not None
    assert [multi_pass.stop_reason] == _gold(f"{prefix}_stop_reason")
    assert [str(multi_pass.passes_executed)] == _gold(f"{prefix}_passes")
    assert [str(multi_pass.converged).upper()] == _gold(f"{prefix}_converged")
    assert [str(result.diagnostics.matched_count)] == _gold(f"{prefix}_matched")


@pytest.mark.parity
def test_clean_layer_batch_matches_golden(dataset: pl.DataFrame, config: Config) -> None:
    result = run_cleaning_layer_batch(
        dataset, _config_with_rule_dirs(config), execution_timestamp_utc=_TIMESTAMP
    )
    _assert_stage(result, "clean")


@pytest.mark.parity
def test_harmonize_layer_batch_matches_golden(dataset: pl.DataFrame, config: Config) -> None:
    result = run_harmonize_layer_batch(
        dataset, _config_with_rule_dirs(config), execution_timestamp_utc=_TIMESTAMP
    )
    _assert_stage(result, "harm")
