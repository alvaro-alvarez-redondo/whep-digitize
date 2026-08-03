"""Stage 0 runner — bootstraps a pipeline run.

Builds the per-run configuration and creates the required directory tree, returning the
:class:`~whep_digitize.setup.config.Config` the downstream stages consume. There is no
dependency check/install step — ``uv`` + ``pyproject.toml`` own the environment, and
importing this package cannot succeed without its dependencies.
"""

from __future__ import annotations

from pathlib import Path

from whep_digitize.setup.config import Config, load_pipeline_config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import create_required_directories
from whep_digitize.setup.helpers.progress import stage_progress
from whep_digitize.setup.options import RuntimeOptions

_MESSAGES = get_pipeline_constants().progress.messages["setup"]


def run_setup_pipeline(
    dataset_name: str | None = None,
    root: Path | str | None = None,
    options: RuntimeOptions | None = None,
) -> Config:
    """Bootstrap a pipeline run: build config and create the directory tree.

    Args:
        dataset_name: Dataset name; defaults to the constant default.
        root: Project root; defaults to the resolved project root.
        options: Runtime options; defaults are used when ``None`` (gates the progress bar).

    Returns:
        The resolved :class:`~whep_digitize.setup.config.Config`.
    """
    resolved_options = options or RuntimeOptions()
    with stage_progress("setup", total=2, enabled=resolved_options.progress_enabled) as progress:
        progress.step(_MESSAGES["load_config"])
        config = load_pipeline_config(dataset_name=dataset_name, root=root)
        progress.step(_MESSAGES["create_dirs"])
        create_required_directories(config)
    return config
