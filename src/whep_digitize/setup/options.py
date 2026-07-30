"""Runtime options — the Python port of the ``whep.*`` R option flags.

In R, behavior is toggled through ``options(whep.* = ...)`` read at call sites. In Python
these become a :class:`RuntimeOptions` settings object, overridable via ``WHEP_*``
environment variables (e.g. ``WHEP_DROP_NA_VALUES=false``).

Deliberate divergence: the R ``whep.run_*_pipeline.auto`` flags exist only because
sourcing an R file auto-executes it. Python modules have no import-time side effects, so
those flags are dropped — stages are invoked by explicit function calls.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeOptions(BaseSettings):
    """Runtime toggles for a pipeline run.

    Attributes:
        drop_na_values: Drop rows whose ``value`` is null during import
            (R ``whep.drop_na_values``, default ``True``).
        progress_enabled: Show the ``rich`` progress display
            (R ``whep.progress.enabled``, default ``True``).
        checkpointing_enabled: Persist per-stage checkpoints for crash recovery
            (R ``whep.checkpointing.enabled``, default ``False``).
        import_parallel_workers: Worker count for parallel import; ``"auto"`` resolves
            to ``min(auto_max, cpu_count - 1)`` and ``1`` forces sequential
            (R ``whep.import.parallel_workers``).
        export_parallel_workers: Worker count for the per-column unique-list workbook writes;
            ``1`` (default) forces sequential, ``"auto"`` / ``N > 1`` write across a
            ``ProcessPoolExecutor`` (deterministic — the workbooks are independent). Sequential
            by default because R's default ``future`` plan is sequential and the workbooks are
            small.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHEP_",
        frozen=True,
        extra="ignore",
    )

    drop_na_values: bool = True
    progress_enabled: bool = True
    checkpointing_enabled: bool = False
    import_parallel_workers: int | Literal["auto"] = "auto"
    export_parallel_workers: int | Literal["auto"] = 1
