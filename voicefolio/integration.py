from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .cache import fetch
from .catalog import Catalog, load_catalog
from .materialize import materialize_wav
from .models import FetchProgress, IntegrityError, MaterializedVoice, ResolvedVoice, VoiceEntry
from .progress import ProgressCallback


def managed_reference(ref: str, *, catalog: Catalog | None = None) -> dict[str, Any]:
    """Return the portable RenderPlan/VoiceRender voice_source mapping for *ref*.

    It intentionally contains no machine-local path. The SHA and source revision pin exact source
    bytes; a renderer WAV derived from FLAC remains a separate runtime artifact.
    """
    entry = (catalog or load_catalog()).get(ref)
    return {
        "kind": "managed_reference",
        "resolver": "voicefolio",
        "value": str(entry.ref),
        "sha256": entry.sha256,
        "source_format": entry.format,
        "source_revision": entry.source_revision,
        "source_repository": entry.source_repository,
        "source_path": entry.source_path,
        "license": entry.license,
        "dataset": entry.dataset,
        "variant": entry.variant,
    }


def validate_voice_source(
    source: Mapping[str, Any], *, catalog: Catalog | None = None
) -> VoiceEntry:
    """Validate persisted managed-reference pins without downloading the WAV."""
    if source.get("kind") != "managed_reference":
        raise IntegrityError("voice source kind must be 'managed_reference'")
    if source.get("resolver") != "voicefolio":
        raise IntegrityError("voice source resolver must be 'voicefolio'")
    ref = source.get("value")
    if not isinstance(ref, str) or not ref.strip():
        raise IntegrityError("Voicefolio voice source requires a non-empty value")
    active_catalog = catalog if catalog is not None else load_catalog()
    try:
        entry = active_catalog.get(ref)
    except ValueError as exc:
        raise IntegrityError(f"invalid Voicefolio voice reference {ref!r}: {exc}") from exc

    expected = {
        "sha256": entry.sha256,
        "source_revision": entry.source_revision,
        "source_repository": entry.source_repository,
        "source_path": entry.source_path,
    }
    for name, catalog_value in expected.items():
        profile_value = source.get(name)
        if profile_value != catalog_value:
            raise IntegrityError(
                f"Voicefolio source pin {name} changed for {ref}: "
                f"profile={profile_value!r}, catalog={catalog_value!r}"
            )
    if "source_format" in source and source["source_format"] != entry.format:
        raise IntegrityError(
            f"Voicefolio source pin source_format changed for {ref}: "
            f"profile={source['source_format']!r}, catalog={entry.format!r}"
        )
    for name in ("license", "dataset", "variant"):
        if name in source and source[name] != getattr(entry, name):
            raise IntegrityError(
                f"Voicefolio source description {name} changed for {ref}: "
                f"profile={source[name]!r}, catalog={getattr(entry, name)!r}"
            )
    return entry


def resolve_voice_source(
    source: Mapping[str, Any],
    *,
    catalog: Catalog | None = None,
    cache_dir: str | Path | None = None,
    offline: bool = False,
    progress: Callable[[FetchProgress], None] | None = None,
    materialization_progress: ProgressCallback | None = None,
) -> ResolvedVoice | MaterializedVoice:
    """Validate a managed reference and resolve its source or renderer WAV."""
    entry = validate_voice_source(source, catalog=catalog)
    if entry.format == "flac":
        return materialize_wav(
            entry,
            cache_dir=cache_dir,
            offline=offline,
            progress=materialization_progress,
            source_progress=progress,
        )
    return fetch(entry, cache_dir=cache_dir, offline=offline, progress=progress)
