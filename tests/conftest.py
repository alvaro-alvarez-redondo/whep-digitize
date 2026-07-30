"""Shared pytest fixtures — the Python analogue of ``tests/test_helper.R``.

Provides an isolated project root, a resolved :class:`Config`, and a small in-memory
long-format frame. Deterministic and side-effect free (temp dirs only).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import polars as pl
import pytest

from whep_digitize.setup.config import Config, load_pipeline_config

_CORPUS = Path(__file__).parent / "fixtures" / "corpus"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An isolated, temporary project root for a test."""
    return tmp_path


@pytest.fixture
def config(project_dir: Path) -> Config:
    """A config rooted at the temporary project directory."""
    return load_pipeline_config(root=project_dir)


@pytest.fixture
def corpus_config(config: Config) -> Config:
    """A config whose raw import folder points at the committed fixture corpus."""
    import_ = dataclasses.replace(config.paths.data.import_, raw=_CORPUS)
    data = dataclasses.replace(config.paths.data, import_=import_)
    return dataclasses.replace(config, paths=dataclasses.replace(config.paths, data=data))


@pytest.fixture
def sample_long_df() -> pl.DataFrame:
    """A small canonical long-format frame (unsorted, with a null value/hemisphere)."""
    return pl.DataFrame(
        {
            "hemisphere": ["north", "north", None],
            "continent": ["europe", "asia", "europe"],
            "polity": ["spain", "japan", "france"],
            "commodity": ["wheat", "rice", "wheat"],
            "variable": ["production", "production", "production"],
            "unit": ["tonnes", "tonnes", "tonnes"],
            "year": ["2000", "2001", "1999"],
            "value": [1.0, 2.0, None],
            "notes": [None, None, None],
            "footnotes": [None, None, None],
            "yearbook": ["fao_2000", "fao_2001", "fao_1999"],
            "document": ["a.xlsx", "b.xlsx", "c.xlsx"],
        }
    )
