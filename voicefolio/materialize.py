"""Deterministic renderer-WAV materialization for pinned FLAC source assets."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .cache import default_cache_dir, fetch, sha256_file, verify_file
from .errors import IntegrityError, MaterializationError, MissingAudioDependencyError
from .models import FetchProgress, MaterializedVoice, ResolvedVoice, VoiceEntry
from .progress import ProgressCallback, ProgressEvent, emit_progress

MATERIALIZATION_RECIPE = "flac-to-wav-v1"
_MAX_MATERIALIZED_BYTES = 1024 * 1024 * 1024
_MAX_CHANNELS = 32
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000
_CHUNK_FRAMES = 65_536
_FLAC_TO_WAV_SUBTYPE = {
    "PCM_S8": ("PCM_U8", 1),
    "PCM_16": ("PCM_16", 2),
    "PCM_24": ("PCM_24", 3),
}
_WAV_SUBTYPES = frozenset({"PCM_U8", "PCM_16", "PCM_24"})


class _ProgressCallbackError(Exception):
    def __init__(self, original: Exception) -> None:
        self.original = original


def _guard_callback(callback: ProgressCallback | None) -> ProgressCallback | None:
    if callback is None:
        return None

    def notify(event: ProgressEvent) -> None:
        try:
            callback(event)
        except Exception as exc:
            raise _ProgressCallbackError(exc) from exc

    return notify


def _materialization_paths(
    source: ResolvedVoice, cache_dir: str | Path | None
) -> tuple[Path, Path]:
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
    directory = root / "materialized" / MATERIALIZATION_RECIPE / source.sha256[:2]
    path = directory / f"{source.sha256}.wav"
    return path, path.with_suffix(".wav.json")


def _emit(
    callback: ProgressCallback | None,
    *,
    phase: str,
    kind: str,
    source: ResolvedVoice,
    completed: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> None:
    emit_progress(
        callback,
        ProgressEvent(
            phase=phase,
            kind=kind,
            completed=completed,
            total=total,
            message=message,
            details={"ref": str(source.ref), "source_sha256": source.sha256},
        ),
    )


def _fetch_progress_adapter(
    callback: ProgressCallback | None,
) -> Callable[[FetchProgress], None] | None:
    if callback is None:
        return None

    def notify(event: FetchProgress) -> None:
        emit_progress(
            callback,
            ProgressEvent(
                phase=event.phase,
                kind="audio.fetch",
                completed=event.completed,
                total=event.total,
                details={"ref": event.ref},
            ),
        )

    return notify


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _cached_materialization(
    source: ResolvedVoice,
    path: Path,
    manifest_path: Path,
) -> MaterializedVoice | None:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            return None
        if (
            raw.get("schema") != 1
            or raw.get("recipe") != MATERIALIZATION_RECIPE
            or raw.get("source_sha256") != source.sha256
            or not _valid_sha256(raw.get("sha256"))
            or raw.get("subtype") not in _WAV_SUBTYPES
        ):
            return None
        size = raw.get("size")
        sample_rate = raw.get("sample_rate")
        channels = raw.get("channels")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or size > _MAX_MATERIALIZED_BYTES
            or isinstance(sample_rate, bool)
            or not isinstance(sample_rate, int)
            or not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE
            or isinstance(channels, bool)
            or not isinstance(channels, int)
            or not 1 <= channels <= _MAX_CHANNELS
        ):
            return None
        if path.stat().st_size != size or sha256_file(path) != raw["sha256"]:
            return None
        return MaterializedVoice(
            source=source,
            path=path,
            sha256=raw["sha256"],
            recipe=MATERIALIZATION_RECIPE,
            sample_rate=sample_rate,
            channels=channels,
            subtype=raw["subtype"],
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_soundfile() -> Any:
    try:
        import soundfile as sf
    except (ImportError, OSError) as exc:
        raise MissingAudioDependencyError(
            "Install voicefolio[audio] to materialize FLAC sources as renderer WAVs."
        ) from exc
    return sf


def materialize_wav(
    entry_or_resolved: VoiceEntry | ResolvedVoice,
    *,
    cache_dir: str | Path | None = None,
    offline: bool = False,
    progress: ProgressCallback | None = None,
    source_progress: Callable[[FetchProgress], None] | None = None,
) -> ResolvedVoice | MaterializedVoice:
    """Return an exact WAV source or a deterministic cached WAV derived from FLAC."""
    source = (
        fetch(
            entry_or_resolved,
            cache_dir=cache_dir,
            offline=offline,
            progress=source_progress or _fetch_progress_adapter(progress),
        )
        if isinstance(entry_or_resolved, VoiceEntry)
        else entry_or_resolved
    )
    verify_file(source.path, source.entry)
    if source.entry.format == "wav":
        return source
    if source.entry.format != "flac":
        raise MaterializationError(
            f"cannot materialize unsupported source format {source.entry.format!r} for {source.ref}"
        )

    output_path, manifest_path = _materialization_paths(source, cache_dir)
    cached = _cached_materialization(source, output_path, manifest_path)
    if cached is not None:
        _emit(
            progress,
            phase="ready",
            kind="audio.materialize",
            source=source,
            completed=1,
            total=1,
        )
        return cached

    sf = _load_soundfile()
    conversion_progress = _guard_callback(progress)
    temporary: Path | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with sf.SoundFile(source.path, mode="r") as reader:
            if reader.format != "FLAC":
                raise MaterializationError(
                    f"pinned FLAC source {source.ref} does not contain FLAC audio"
                )
            source_subtype = reader.subtype
            subtype_mapping = _FLAC_TO_WAV_SUBTYPE.get(source_subtype)
            if subtype_mapping is None:
                raise MaterializationError(
                    f"unsupported FLAC subtype {source_subtype!r} for {source.ref}"
                )
            wav_subtype, bytes_per_sample = subtype_mapping
            sample_rate = int(reader.samplerate)
            channels = int(reader.channels)
            frames = int(reader.frames)
            if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
                raise MaterializationError(
                    f"unsupported sample rate {sample_rate} Hz for {source.ref}"
                )
            if not 1 <= channels <= _MAX_CHANNELS or frames <= 0:
                raise MaterializationError(
                    f"unsupported FLAC audio shape ({frames} frames, {channels} channels) for {source.ref}"
                )
            pcm_bytes = frames * channels * bytes_per_sample
            if pcm_bytes + 4096 > _MAX_MATERIALIZED_BYTES:
                raise MaterializationError(
                    f"materialized audio for {source.ref} exceeds {_MAX_MATERIALIZED_BYTES} bytes"
                )

            with tempfile.NamedTemporaryFile(
                dir=output_path.parent, delete=False, suffix=".wav"
            ) as tmp:
                temporary = Path(tmp.name)
            _emit(
                conversion_progress,
                phase="convert",
                kind="audio.materialize",
                source=source,
                completed=0,
                total=frames,
            )
            frames_written = 0
            with sf.SoundFile(
                temporary,
                mode="w",
                samplerate=sample_rate,
                channels=channels,
                format="WAV",
                subtype=wav_subtype,
                endian="LITTLE",
            ) as writer:
                while True:
                    block = reader.read(
                        frames=_CHUNK_FRAMES,
                        dtype="float64",
                        always_2d=True,
                    )
                    if block.shape[0] == 0:
                        break
                    block_frames = int(block.shape[0])
                    frames_written += block_frames
                    if frames_written > frames:
                        raise MaterializationError(
                            f"FLAC decoder exceeded declared frame count for {source.ref}"
                        )
                    writer.write(block)
                    _emit(
                        conversion_progress,
                        phase="convert",
                        kind="audio.materialize",
                        source=source,
                        completed=frames_written,
                        total=frames,
                    )
            if frames_written != frames:
                raise MaterializationError(
                    f"FLAC decoder returned {frames_written} of {frames} frames for {source.ref}"
                )

        if temporary.stat().st_size > _MAX_MATERIALIZED_BYTES:
            raise MaterializationError(
                f"materialized audio for {source.ref} exceeds {_MAX_MATERIALIZED_BYTES} bytes"
            )
        info = sf.info(temporary)
        if (
            info.format != "WAV"
            or info.subtype != wav_subtype
            or info.samplerate != sample_rate
            or info.channels != channels
            or info.frames != frames
        ):
            raise MaterializationError(f"materialized WAV metadata changed for {source.ref}")
        output_sha256 = sha256_file(temporary)
        output_size = temporary.stat().st_size
        os.replace(temporary, output_path)
        _write_manifest(
            manifest_path,
            {
                "schema": 1,
                "recipe": MATERIALIZATION_RECIPE,
                "source_sha256": source.sha256,
                "sha256": output_sha256,
                "size": output_size,
                "sample_rate": sample_rate,
                "channels": channels,
                "subtype": wav_subtype,
            },
        )
        _emit(
            conversion_progress,
            phase="ready",
            kind="audio.materialize",
            source=source,
            completed=frames,
            total=frames,
        )
        return MaterializedVoice(
            source=source,
            path=output_path,
            sha256=output_sha256,
            recipe=MATERIALIZATION_RECIPE,
            sample_rate=sample_rate,
            channels=channels,
            subtype=wav_subtype,
        )
    except _ProgressCallbackError as exc:
        raise exc.original
    except (IntegrityError, MaterializationError, MissingAudioDependencyError):
        raise
    except OSError as exc:
        raise MaterializationError(
            f"unable to materialize WAV for {source.ref}: {exc}"
        ) from exc
    except Exception as exc:
        raise MaterializationError(f"unable to decode/materialize {source.ref}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
