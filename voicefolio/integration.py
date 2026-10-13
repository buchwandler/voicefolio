from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .cache import fetch
from .catalog import Catalog, load_catalog
from .models import IntegrityError, ResolvedVoice


def managed_reference(ref: str, *, catalog: Catalog | None = None) -> dict[str, Any]:
    """Return the portable RenderPlan/VoiceRender voice_source mapping for *ref*.

    It intentionally contains no machine-local path. The SHA and source revision pin the
    exact WAV while the stable ref remains convenient for plans and profiles.
    """
    entry = (catalog or load_catalog()).get(ref)
    return {
        "kind": "managed_reference",
        "resolver": "voicefolio",
        "value": str(entry.ref),
        "sha256": entry.sha256,
        "source_revision": entry.source_revision,
        "source_repository": entry.source_repository,
        "source_path": entry.source_path,
        "license": entry.license,
        "dataset": entry.dataset,
        "variant": entry.variant,
    }


def resolve_voice_source(
    source: Mapping[str, Any],
    *,
    catalog: Catalog | None = None,
    cache_dir: str | Path | None = None,
    offline: bool = False,
) -> ResolvedVoice:
    """Resolve a Voicefolio managed_reference to a verified local WAV.

    This is the intended integration point for VoiceRender. It revalidates every pin
    stored in the RenderProfile before returning a path.
    """
    if source.get("kind") != "managed_reference" or source.get("resolver") != "voicefolio":
        raise ValueError("voice source is not a Voicefolio managed reference")
    ref = source.get("value")
    if not isinstance(ref, str) or not ref:
        raise ValueError("Voicefolio voice source requires a non-empty value")
    entry = (catalog or load_catalog()).get(ref)
    expected = {
        "sha256": entry.sha256,
        "source_revision": entry.source_revision,
        "source_repository": entry.source_repository,
        "source_path": entry.source_path,
    }
    for name, actual_expected in expected.items():
        value = source.get(name)
        if value != actual_expected:
            raise IntegrityError(
                f"Voicefolio source pin {name} changed for {ref}: "
                f"profile={value!r}, catalog={actual_expected!r}"
            )
    return fetch(entry, cache_dir=cache_dir, offline=offline)
