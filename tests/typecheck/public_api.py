from __future__ import annotations

from collections.abc import Callable

from voicefolio import (
    Catalog,
    FetchProgress,
    MaterializedVoice,
    ProgressCallback,
    ProgressEvent,
    ResolvedVoice,
    VoiceEntry,
    VoiceRef,
    managed_reference,
    resolve_voice_source,
    validate_voice_source,
)


def public_consumer(
    catalog: Catalog,
    progress: Callable[[FetchProgress], None],
    materialization_progress: ProgressCallback,
) -> tuple[VoiceEntry, ResolvedVoice | MaterializedVoice, VoiceRef]:
    entry: VoiceEntry = catalog.get("kyutai-tts-voices:voice-donations/0a67")
    rows: tuple[VoiceEntry, ...] = catalog.list(
        namespace=entry.ref.namespace,
        speaker="speaker",
        gender="female",
        pitch_band="low",
        emotion="calm",
    )
    reference: VoiceRef = entry.ref
    mapping = managed_reference(str(reference), catalog=catalog)
    validated: VoiceEntry = validate_voice_source(mapping, catalog=catalog)
    resolved: ResolvedVoice | MaterializedVoice = resolve_voice_source(
        mapping,
        catalog=catalog,
        offline=True,
        progress=progress,
        materialization_progress=materialization_progress,
    )
    event: ProgressEvent | None = None
    _ = rows, event
    return validated, resolved, reference
