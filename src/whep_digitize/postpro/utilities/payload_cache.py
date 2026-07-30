"""Postpro / utilities — rule-payload runtime cache.

The Python port of ``r/2-postpro_pipeline/21-postpro_utilities/21-runtime-cache.R``: a two-level
(memory + disk) cache of coerced rule payloads, keyed by an md5 fingerprint of the stage's
ordered rule files. **Disabled by default** (the :class:`RuntimeCache` constant); when off,
:func:`get_cached_stage_payload_bundle` just builds the payloads.

Divergences from R (all deliberate):

* R's ``new.env`` module cache becomes a module-level ``dict`` (the sanctioned pattern — see
  ``.claude/docs/r-to-python-mapping.md``).
* R persisted with ``saveRDS``; the disk layer here uses ``pickle`` (the direct arbitrary-object
  analogue — a payload bundle is a nested structure of frames + metadata that parquet cannot
  represent). It is only touched when the cache is explicitly enabled.
* R auto-enabled the cache whenever a ``runtime_cache_dir`` was configured; this port keeps it
  off by default (the documented Python behavior), overridable via the resolved settings.
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from whep_digitize.postpro.rule_engine.schema_validation import coerce_rule_schema
from whep_digitize.postpro.utilities.stage_definitions import validate_postpro_stage_name
from whep_digitize.postpro.utilities.templates import (
    discover_stage_rule_files,
    load_stage_rule_payloads,
)
from whep_digitize.setup.config import Config
from whep_digitize.setup.constants import get_pipeline_constants
from whep_digitize.setup.directories import ensure_directories_exist

_CONSTANTS = get_pipeline_constants()
# Sanctioned module-level cache (R ``.stage_payload_bundle_cache`` env). Keyed by cache key.
_MEMORY_CACHE: dict[str, StagePayloadBundle] = {}


@dataclass(frozen=True, slots=True)
class RuntimeCacheSettings:
    """Resolved runtime-cache settings (R ``resolve_stage_runtime_cache_settings``).

    Attributes:
        enabled: Whether the cache is active (off by default).
        cache_file_name: The on-disk cache file name (under ``runtime_cache_dir``).
        max_entries: Maximum retained cache entries (deterministic prune keeps the lowest keys).
    """

    enabled: bool
    cache_file_name: str
    max_entries: int


@dataclass(frozen=True, slots=True)
class CanonicalPayload:
    """One rule file coerced to the canonical schema.

    Attributes:
        rule_file_id: The rule file's base name.
        rule_file_path: The rule file's absolute path.
        canonical_rules: The coerced canonical rule table.
    """

    rule_file_id: str
    rule_file_path: str
    canonical_rules: pl.DataFrame


@dataclass(frozen=True, slots=True)
class StagePayloadBundle:
    """A stage's cached canonical payloads (R ``list(cache_key, canonical_payloads)``).

    Attributes:
        cache_key: The md5-fingerprint cache key the bundle was built for.
        canonical_payloads: The coerced payloads, in rule-file order.
    """

    cache_key: str
    canonical_payloads: tuple[CanonicalPayload, ...]


def resolve_stage_runtime_cache_settings(config: Config) -> RuntimeCacheSettings:
    """Resolve the runtime-cache settings from the config's post-processing constants.

    The Python port of R ``resolve_stage_runtime_cache_settings`` (kept off by default).

    Args:
        config: The resolved pipeline configuration.

    Returns:
        The resolved :class:`RuntimeCacheSettings`.
    """
    runtime_cache = config.postpro.runtime_cache
    return RuntimeCacheSettings(
        enabled=runtime_cache.enabled,
        cache_file_name=runtime_cache.cache_file_name,
        max_entries=runtime_cache.max_entries,
    )


def build_stage_payload_cache_key(config: Config, stage_name: str) -> str:
    """Build the deterministic cache key from the stage's ordered rule-file md5 fingerprints.

    The Python port of R ``build_stage_payload_cache_key``: ``<stage>::<file>::<md5>||...@@<dir>``,
    or ``<stage>::<no_rule_files>`` when the stage has none.

    Args:
        config: The resolved pipeline configuration.
        stage_name: The execution stage (``clean`` or ``harmonize``).

    Returns:
        The cache key.
    """
    stage = validate_postpro_stage_name(stage_name)
    import_dir = getattr(
        config.paths.data.import_, {"clean": "cleaning", "harmonize": "harmonization"}[stage]
    )
    ordered_files = discover_stage_rule_files(config, stage)
    if not ordered_files:
        return f"{stage}::<no_rule_files>"

    fingerprints = [f"{path.name}::{_md5_file(path)}" for path in ordered_files]
    return f"{stage}::{'||'.join(fingerprints)}@@{import_dir}"


def prune_runtime_cache_entries(
    cache_entries: dict[str, StagePayloadBundle], max_entries: int
) -> dict[str, StagePayloadBundle]:
    """Deterministically prune to ``max_entries`` by keeping the lowest-sorted keys.

    The Python port of R ``prune_runtime_cache_entries``.

    Args:
        cache_entries: The cache entries to prune.
        max_entries: Maximum entries to retain (must be positive).

    Returns:
        The pruned entries (a new dict; the input is not mutated).
    """
    if len(cache_entries) <= max_entries:
        return dict(cache_entries)
    keep_keys = sorted(cache_entries)[:max_entries]
    return {key: cache_entries[key] for key in keep_keys}


def get_cached_stage_payload_bundle(
    config: Config, stage_name: str, *, settings: RuntimeCacheSettings | None = None
) -> StagePayloadBundle:
    """Return the stage's canonical payload bundle, via the two-level cache when enabled.

    The Python port of R ``get_cached_stage_payload_bundle``: memory cache, then disk cache, then
    build-and-persist. When the cache is disabled (the default) the bundle is built each call.

    Args:
        config: The resolved pipeline configuration.
        stage_name: The execution stage (``clean`` or ``harmonize``).
        settings: Optional pre-resolved settings (defaults to
            :func:`resolve_stage_runtime_cache_settings`); accepted for testability.

    Returns:
        The :class:`StagePayloadBundle` for the stage.
    """
    stage = validate_postpro_stage_name(stage_name)
    resolved = settings if settings is not None else resolve_stage_runtime_cache_settings(config)
    cache_key = build_stage_payload_cache_key(config, stage)

    if not resolved.enabled:
        return StagePayloadBundle(cache_key, _build_canonical_payloads(config, stage))

    if cache_key in _MEMORY_CACHE:
        return _MEMORY_CACHE[cache_key]

    disk_bundle = _load_bundle_from_disk(config, resolved, cache_key)
    if disk_bundle is not None:
        _store_in_memory(cache_key, disk_bundle, resolved.max_entries)
        return disk_bundle

    bundle = StagePayloadBundle(cache_key, _build_canonical_payloads(config, stage))
    _store_in_memory(cache_key, bundle, resolved.max_entries)
    _persist_bundle_to_disk(config, resolved, cache_key, bundle)
    return bundle


def clear_stage_payload_memory_cache() -> None:
    """Empty the in-memory payload cache (test/reset helper; the disk cache is untouched)."""
    _MEMORY_CACHE.clear()


# --------------------------------------------------------------------------- private helpers


def _md5_file(path: Path) -> str:
    """Return the hex md5 digest of a file's bytes (R ``tools::md5sum``)."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def _build_canonical_payloads(config: Config, stage: str) -> tuple[CanonicalPayload, ...]:
    """Load and coerce every rule payload for a stage."""
    return tuple(
        CanonicalPayload(
            rule_file_id=payload.rule_file_id,
            rule_file_path=payload.rule_file_path,
            canonical_rules=coerce_rule_schema(
                payload.raw_rules, stage, payload.rule_file_id, payload.rule_file_path
            ),
        )
        for payload in load_stage_rule_payloads(config, stage)
    )


def _store_in_memory(cache_key: str, bundle: StagePayloadBundle, max_entries: int) -> None:
    """Insert a bundle into the memory cache and prune it in place to ``max_entries``."""
    _MEMORY_CACHE[cache_key] = bundle
    pruned = prune_runtime_cache_entries(_MEMORY_CACHE, max_entries)
    if len(pruned) != len(_MEMORY_CACHE):
        _MEMORY_CACHE.clear()
        _MEMORY_CACHE.update(pruned)


def _cache_file_path(config: Config, settings: RuntimeCacheSettings) -> Path:
    """Return the on-disk cache file path under the runtime-cache directory."""
    return config.paths.data.audit.runtime_cache_dir / settings.cache_file_name


def _read_disk_entries(
    config: Config, settings: RuntimeCacheSettings
) -> dict[str, StagePayloadBundle]:
    """Read (and prune) the disk cache; return an empty dict when disabled/absent/unreadable."""
    path = _cache_file_path(config, settings)
    if not settings.enabled or not path.is_file():
        return {}
    try:
        loaded = pickle.loads(path.read_bytes())
    except (pickle.UnpicklingError, EOFError, ValueError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return prune_runtime_cache_entries(loaded, settings.max_entries)


def _load_bundle_from_disk(
    config: Config, settings: RuntimeCacheSettings, cache_key: str
) -> StagePayloadBundle | None:
    """Load one bundle from the disk cache by key, or ``None`` if absent."""
    return _read_disk_entries(config, settings).get(cache_key)


def _persist_bundle_to_disk(
    config: Config, settings: RuntimeCacheSettings, cache_key: str, bundle: StagePayloadBundle
) -> None:
    """Persist one bundle under its key into the (pruned) disk cache."""
    if not settings.enabled:
        return
    entries = _read_disk_entries(config, settings)
    entries[cache_key] = bundle
    pruned = prune_runtime_cache_entries(entries, settings.max_entries)
    ensure_directories_exist([config.paths.data.audit.runtime_cache_dir])
    _cache_file_path(config, settings).write_bytes(pickle.dumps(pruned))
