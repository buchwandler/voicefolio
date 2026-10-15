from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from voicefolio.errors import MissingAudioDependencyError
from voicefolio.materialize import MATERIALIZATION_RECIPE, materialize_wav
from voicefolio.models import MaterializedVoice, ResolvedVoice, VoiceEntry, VoiceRef
from voicefolio.progress import ProgressEvent


def _flac_entry(tmp_path: Path, samples: np.ndarray, subtype: str = "PCM_16") -> VoiceEntry:
    source_path = tmp_path / "source.flac"
    sf.write(source_path, samples, 24_000, format="FLAC", subtype=subtype)
    payload = source_path.read_bytes()
    return VoiceEntry(
        ref=VoiceRef("voice-zero", "fixture_voice"),
        dataset="voice-zero",
        language="en",
        variant="original",
        format="flac",
        url=source_path.as_uri(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source_repository="VoiceActivity/Voice-Zero",
        source_revision="a" * 40,
        source_path="voice-zero/fixture_voice.flac",
        license="CC0-1.0",
    )


@pytest.mark.parametrize(
    ("source_subtype", "expected_wav_subtype"),
    [("PCM_S8", "PCM_U8"), ("PCM_24", "PCM_24")],
)
def test_materialize_preserves_supported_flac_integer_precision(
    tmp_path: Path,
    source_subtype: str,
    expected_wav_subtype: str,
) -> None:
    samples = np.array([-1.0, -0.5, -0.125, 0.0, 0.125, 0.5, 0.875], dtype=np.float64)
    entry = _flac_entry(tmp_path, samples, subtype=source_subtype)

    result = materialize_wav(entry, cache_dir=tmp_path / "cache")

    assert isinstance(result, MaterializedVoice)
    assert result.subtype == expected_wav_subtype
    source_samples, _ = sf.read(result.source.path, dtype="float64", always_2d=False)
    output_samples, _ = sf.read(result.path, dtype="float64", always_2d=False)
    np.testing.assert_array_equal(output_samples, source_samples)


def test_materialize_flac_preserves_source_and_renderer_digests(tmp_path: Path) -> None:
    samples = np.array([0, 100, -100, 32767, -32768, 2048, -2048], dtype=np.int16)
    entry = _flac_entry(tmp_path, samples)
    cache_dir = tmp_path / "cache"

    result = materialize_wav(entry, cache_dir=cache_dir)

    assert isinstance(result, MaterializedVoice)
    assert result.source.sha256 == entry.sha256
    assert result.source_sha256 == entry.sha256
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert result.sha256 != entry.sha256
    assert result.recipe == MATERIALIZATION_RECIPE
    assert result.path.suffix == ".wav"
    assert (result.sample_rate, result.channels, result.subtype) == (24_000, 1, "PCM_16")
    source_samples, _ = sf.read(result.source.path, dtype="int16", always_2d=False)
    output_samples, _ = sf.read(result.path, dtype="int16", always_2d=False)
    np.testing.assert_array_equal(output_samples, source_samples)
    first_bytes = result.path.read_bytes()
    result.path.unlink()
    result.path.with_suffix(".wav.json").unlink()
    rebuilt = materialize_wav(entry, cache_dir=cache_dir)
    assert isinstance(rebuilt, MaterializedVoice)
    assert rebuilt.path.read_bytes() == first_bytes
    assert rebuilt.sha256 == result.sha256
    assert isinstance(materialize_wav(entry, cache_dir=cache_dir), MaterializedVoice)


def test_materialization_cache_is_reused_and_corruption_is_rebuilt(tmp_path: Path) -> None:
    samples = np.arange(-100, 100, dtype=np.int16)
    entry = _flac_entry(tmp_path, samples)
    cache_dir = tmp_path / "cache"
    first = materialize_wav(entry, cache_dir=cache_dir)
    assert isinstance(first, MaterializedVoice)

    with patch(
        "voicefolio.materialize._load_soundfile", side_effect=AssertionError("cache miss")
    ):
        reused = materialize_wav(entry, cache_dir=cache_dir)
    assert reused == first

    first.path.write_bytes(b"corrupt renderer WAV")
    rebuilt = materialize_wav(entry, cache_dir=cache_dir)
    assert isinstance(rebuilt, MaterializedVoice)
    assert rebuilt.sha256 == first.sha256
    assert rebuilt.path.read_bytes()[:4] == b"RIFF"


def test_materialize_wav_source_returns_exact_resolved_voice(tmp_path: Path) -> None:
    payload = b"not-decoded-but-integrity-pinned-wav-bytes"
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(payload)
    entry = VoiceEntry(
        ref=VoiceRef("fine-read-it-voices", "F002"),
        dataset="fine-read-it-voices",
        language="en",
        variant="original",
        format="wav",
        url=source_path.as_uri(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source_repository="zloezlo/fine-read-it-voices",
        source_revision="b" * 40,
        source_path="F002.wav",
        license="CC-BY-4.0",
    )

    result = materialize_wav(entry, cache_dir=tmp_path / "cache")

    assert isinstance(result, ResolvedVoice)
    assert result.path.read_bytes() == payload
    assert result.sha256 == entry.sha256


def test_materialization_reports_missing_audio_extra(tmp_path: Path) -> None:
    payload = b"pinned but intentionally undecoded FLAC"
    source_path = tmp_path / "source.flac"
    source_path.write_bytes(payload)
    entry = VoiceEntry(
        ref=VoiceRef("voice-zero", "fixture_voice"),
        dataset="voice-zero",
        language="en",
        variant="original",
        format="flac",
        url=source_path.as_uri(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source_repository="VoiceActivity/Voice-Zero",
        source_revision="a" * 40,
        source_path="voice-zero/fixture_voice.flac",
        license="CC0-1.0",
    )
    with (
        patch(
            "voicefolio.materialize._load_soundfile",
            side_effect=MissingAudioDependencyError("Install voicefolio[audio]."),
        ),
        pytest.raises(MissingAudioDependencyError, match=r"voicefolio\[audio\]"),
    ):
        materialize_wav(entry, cache_dir=tmp_path / "cache")


def test_materialization_progress_callback_exceptions_propagate(tmp_path: Path) -> None:
    entry = _flac_entry(tmp_path, np.arange(32, dtype=np.int16))
    callback_error = RuntimeError("progress consumer failed")

    def fail(_event: ProgressEvent) -> None:
        raise callback_error

    with pytest.raises(RuntimeError) as raised:
        materialize_wav(entry, cache_dir=tmp_path / "cache", progress=fail)
    assert raised.value is callback_error
