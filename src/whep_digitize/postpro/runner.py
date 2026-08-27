"""Stage 2 runner.

Runs the deterministic 9-step post-processing orchestration: audit the raw import frame, resolve
the audit roots, generate the rule templates, collect + assert the preflight checks, then
run the clean → standardize-units → harmonize layers (each sorted to the canonical row order),
and finally persist the per-stage audit workbooks. Returns a typed
:class:`~whep_digitize.contracts.PostproResult` carrying the clean / normalize / harmonize
frames and the aggregate diagnostics.

Progress reporting emits nine hard ticks through a gated :func:`stage_progress` bar — one per
orchestration step, with no per-pass pulses. The diagnostics ``outputs`` mapping is flat: the
four persisted audit paths sit at the top level alongside the resolved directories, the
template, and the data-audit path.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from whep_digitize.contracts import LayerDiagnostics, PostproDiagnostics, PostproResult
from whep_digitize.postpro.audit.audit import audit_dataset
from whep_digitize.postpro.clean_harmonize.layer_runner import (
    run_cleaning_layer_batch,
    run_harmonize_layer_batch,
)
from whep_digitize.postpro.diagnostics.persist import persist_postpro_audit
from whep_digitize.postpro.diagnostics.preflight import (
    assert_postpro_preflight,
    collect_postpro_preflight,
)
from whep_digitize.postpro.standardize_units.orchestration import (
    StandardizeDiagnostics,
    run_standardize_units_layer_batch,
)
from whep_digitize.postpro.utilities.audit_roots import (
    PostproAuditPaths,
    get_postpro_audit_paths,
)
from whep_digitize.postpro.utilities.templates import generate_postpro_rule_templates
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.helpers.frames import canonicalize_semicolon_string_columns
from whep_digitize.setup.helpers.progress import stage_progress
from whep_digitize.setup.helpers.sorting import sort_pipeline_stage_df
from whep_digitize.setup.options import RuntimeOptions

_DEFAULT_DATASET_NAME = get_pipeline_constants().dataset_default_name
_MESSAGES = get_pipeline_constants().progress.messages["postpro"]


def run_postpro_pipeline(
    raw: pl.DataFrame,
    config: Config,
    dataset_name: str | None = None,
    options: RuntimeOptions | None = None,
) -> PostproResult:
    """Audit, clean, standardize units, and harmonize the raw import frame.

    The nine deterministic steps: audit → resolve audit roots → templates → collect preflight →
    assert preflight → clean → standardize → harmonize → persist. Each layer frame is sorted to
    the canonical row order by :func:`sort_pipeline_stage_df` before feeding the next stage.

    Args:
        raw: The raw long frame from the ingest stage.
        config: The resolved pipeline configuration.
        dataset_name: Dataset identifier for audit/event metadata; defaults to
            ``get_pipeline_constants().dataset_default_name`` when ``None``.
        options: Runtime options; accepted for a uniform cross-stage signature. This stage takes
            no options of its own and reads every control from ``config``.

    Returns:
        A :class:`PostproResult` with the harmonized / clean / normalize frames and the
        aggregate :class:`~whep_digitize.contracts.PostproDiagnostics`.

    Raises:
        WhepError: If preflight checks fail, or a multi-pass cycle is detected under the
            ``"abort"`` cycle policy.
    """
    resolved_options = options or RuntimeOptions()
    resolved_dataset_name = dataset_name if dataset_name is not None else _DEFAULT_DATASET_NAME

    with stage_progress("postpro", total=9, enabled=resolved_options.progress_enabled) as progress:
        # 1. audit — coerce ``value`` to Float64, export invalid-cell highlights (rows kept).
        progress.step(_MESSAGES["audit"])
        raw_df = _canonicalize_stage_frame(raw)
        audited = audit_dataset(raw_df, config).audited

        # 2. resolve the audit roots (the directory tree itself is created by step 3).
        progress.step(_MESSAGES["init_dirs"])
        audit_paths = get_postpro_audit_paths(config)

        # 3. templates — create the audit subtree and write the clean/harmonize rule template.
        progress.step(_MESSAGES["templates"])
        template_path = generate_postpro_rule_templates(config, overwrite=True)

        # 4. + 5. preflight — collect the rule-directory / naming / expected-column checks + assert.
        progress.step(_MESSAGES["collect_preflight"])
        preflight = collect_postpro_preflight(config, dataset_columns=audited.columns)
        progress.step(_MESSAGES["assert_preflight"])
        assert_postpro_preflight(preflight)

        # 6. clean layer (multi-pass), then canonical sort.
        progress.step(_MESSAGES["clean"])
        clean_layer = run_cleaning_layer_batch(audited, config, dataset_name=resolved_dataset_name)
        clean_df = _canonicalize_stage_frame(clean_layer.data)

        # 7. standardize-units layer, then canonical sort.
        progress.step(_MESSAGES["standardize"])
        standardize_layer = run_standardize_units_layer_batch(clean_df, config)
        normalize_df = _canonicalize_stage_frame(standardize_layer.data)

        # 8. harmonize layer (multi-pass) on the normalized frame, then canonical sort.
        progress.step(_MESSAGES["harmonize"])
        harmonize_layer = run_harmonize_layer_batch(
            normalize_df, config, dataset_name=resolved_dataset_name
        )
        harmonize_df = _canonicalize_stage_frame(harmonize_layer.data)

        # 9. persist per-stage audit workbooks + the last-rule-wins overwrite subset.
        progress.step(_MESSAGES["persist"])
        audit_report_paths = persist_postpro_audit(
            clean_audit_df=clean_layer.audit,
            harmonize_audit_df=harmonize_layer.audit,
            standardize_audit_df=standardize_layer.audit,
            standardize_rules_df=standardize_layer.layer_rules,
            final_stage_df=harmonize_df,
            last_rule_wins_overwrites_df=harmonize_layer.overwrite_events,
            config=config,
            standardize_matched_rule_counts_df=standardize_layer.matched_rule_counts,
        )

    diagnostics = PostproDiagnostics(
        clean=clean_layer.diagnostics,
        standardize_units=_as_layer_diagnostics(standardize_layer.diagnostics),
        harmonize=harmonize_layer.diagnostics,
        report_paths=_build_report_paths(audit_paths, template_path, audit_report_paths, config),
    )
    return PostproResult(
        harmonize=harmonize_df,
        clean=clean_df,
        normalize=normalize_df,
        diagnostics=diagnostics,
    )


def _canonicalize_stage_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Canonicalize semicolon-token cells, then sort by the canonical row order."""
    return sort_pipeline_stage_df(canonicalize_semicolon_string_columns(frame))


def _as_layer_diagnostics(standardize: StandardizeDiagnostics) -> LayerDiagnostics:
    """Reduce the richer standardize diagnostics to the shared layer contract (no multi-pass)."""
    return LayerDiagnostics(
        matched_count=standardize.matched_count,
        unmatched_count=standardize.unmatched_count,
        status=standardize.status,
        messages=standardize.messages,
        multi_pass=None,
    )


def _build_report_paths(
    audit_paths: PostproAuditPaths,
    template_path: Path,
    persisted_paths: dict[str, Path],
    config: Config,
) -> dict[str, Path]:
    """Assemble the flat diagnostics ``report_paths`` mapping."""
    return {
        **persisted_paths,
        "audit_root_dir": audit_paths.audit_root_dir,
        "audit_dir": audit_paths.audit_dir,
        "diagnostics_dir": audit_paths.diagnostics_dir,
        "templates_dir": audit_paths.templates_dir,
        "runtime_cache_dir": audit_paths.runtime_cache_dir,
        "clean_harmonize_template_path": template_path,
        "data_audit_report_path": config.paths.data.audit.audit_file_path,
    }
