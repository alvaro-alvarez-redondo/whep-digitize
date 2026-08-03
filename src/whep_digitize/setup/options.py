"""Runtime options — the per-run behavior toggles.

Behavior is toggled through the :class:`RuntimeOptions` settings object, overridable via
``WHEP_*`` environment variables (e.g. ``WHEP_DROP_NA_VALUES=false``).

There is no "auto-run on import" toggle: modules have no import-time side effects, and
every stage is invoked by an explicit function call.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeOptions(BaseSettings):
    """Runtime toggles for a pipeline run.

    Attributes:
        drop_na_values: Drop rows whose ``value`` is null during import
            (default ``True``).
        progress_enabled: Show the ``rich`` progress display
            (default ``True``).
        checkpointing_enabled: Persist per-stage checkpoints for crash recovery
            (default ``False``).
        import_parallel_workers: Worker count for parallel import; ``"auto"`` resolves
            to ``min(auto_max, cpu_count - 1)`` and ``1`` forces sequential.
        export_parallel_workers: Worker count for the per-column unique-list workbook writes;
            ``1`` (default) forces sequential, ``"auto"`` / ``N > 1`` write across a
            ``ProcessPoolExecutor`` (deterministic — the workbooks are independent). Sequential
            by default because the workbooks are small, so the process pool rarely pays off.
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
