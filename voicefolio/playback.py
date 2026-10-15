from __future__ import annotations

from pathlib import Path

from .models import PlaybackError


def play_audio(path: str | Path, *, device: str | int | None = None) -> None:
    """Synchronously play a local WAV or FLAC through native audio output."""
    try:
        import sounddevice as sd
        import soundfile as sf
    except (ImportError, OSError) as exc:
        raise PlaybackError("Install voicefolio[playback] for native preview.") from exc

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


def play_wav(path: str | Path, *, device: str | int | None = None) -> None:
    """Compatibility wrapper for the historical WAV-only playback function."""
    play_audio(path, device=device)
