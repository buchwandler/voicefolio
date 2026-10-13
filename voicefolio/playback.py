from __future__ import annotations

from pathlib import Path

from .models import PlaybackError


def play_wav(path: str | Path, *, device: str | int | None = None) -> None:
    """Synchronously play a local WAV through the native sounddevice backend."""
    try:
        import sounddevice as sd  # type: ignore[import-untyped]
        import soundfile as sf  # type: ignore[import-untyped]
    except (ImportError, OSError) as exc:
        raise PlaybackError(f"native audio playback is unavailable: {exc}") from exc

    audio_path = Path(path)
    try:
        data, sample_rate = sf.read(
            audio_path,
            dtype="float32",
            always_2d=False,
        )
        sd.play(data, sample_rate, device=device)
        sd.wait()
    except Exception as exc:
        raise PlaybackError(f"cannot play {audio_path}: {exc}") from exc
