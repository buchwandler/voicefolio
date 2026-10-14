from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from voicefolio.models import PlaybackError
from voicefolio.playback import play_wav


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def test_play_wav_uses_native_backend_synchronously(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    audio_path = tmp_path / "voice.wav"
    audio = object()
    calls: list[tuple[Any, ...]] = []

    def read(path: Path, *, dtype: str, always_2d: bool) -> tuple[object, int]:
        calls.append(("read", path, dtype, always_2d))
        return audio, 24000

    def play(data: object, sample_rate: int, *, device: str | int | None) -> None:
        calls.append(("play", data, sample_rate, device))

    def wait() -> None:
        calls.append(("wait",))

    monkeypatch.setitem(sys.modules, "soundfile", _module("soundfile", read=read))
    monkeypatch.setitem(
        sys.modules, "sounddevice", _module("sounddevice", play=play, wait=wait)
    )

    play_wav(audio_path, device="USB Output")

    assert calls == [
        ("read", audio_path, "float32", False),
        ("play", audio, 24000, "USB Output"),
        ("wait",),
    ]


@pytest.mark.parametrize("failure", ["decoder", "backend"])
def test_play_wav_wraps_decoder_and_backend_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
):
    def read(*args: Any, **kwargs: Any) -> tuple[object, int]:
        if failure == "decoder":
            raise RuntimeError("bad WAV")
        return object(), 24000

    def play(*args: Any, **kwargs: Any) -> None:
        if failure == "backend":
            raise RuntimeError("PortAudio unavailable")

    monkeypatch.setitem(sys.modules, "soundfile", _module("soundfile", read=read))
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        _module("sounddevice", play=play, wait=lambda: None),
    )

    with pytest.raises(PlaybackError, match="cannot play"):
        play_wav(tmp_path / "voice.wav")


def test_missing_playback_extra_has_install_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_import = builtins.__import__

    def import_without_playback(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"sounddevice", "soundfile"}:
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_playback)
    with pytest.raises(
        PlaybackError, match=r"Install voicefolio\[playback\] for native preview"
    ):
        play_wav(tmp_path / "voice.wav")
