from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from typer.testing import CliRunner

from voicefolio import cli
from voicefolio.catalog import Catalog
from voicefolio.models import VoiceEntry, VoiceRef


def _entry(source_path: Path, audio_format: str, payload: bytes) -> VoiceEntry:
    suffix = audio_format
    return VoiceEntry(
        ref=VoiceRef("voice-zero", "fixture_voice"),
        dataset="voice-zero",
        language="en",
        variant="original",
        format=audio_format,
        url=source_path.as_uri(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source_repository="VoiceActivity/Voice-Zero",
        source_revision="a" * 40,
        source_path=f"voice-zero/fixture_voice.{suffix}",
        license="CC0-1.0",
    )


def test_wav_export_remains_byte_exact(monkeypatch, tmp_path: Path) -> None:
    payload = b"RIFF exact legacy WAV payload"
    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    entry = _entry(source, "wav", payload)
    monkeypatch.setattr(cli, "_catalog", lambda _paths: Catalog([entry]))
    output = tmp_path / "legacy-export.wav"

    result = CliRunner().invoke(cli.app, ["export", str(entry.ref), "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == payload
    manifest = json.loads(
        (tmp_path / "legacy-export.wav.voicefolio.json").read_text(encoding="utf-8")
    )
    assert manifest["sha256"] == entry.sha256
    assert manifest["source_sha256"] == entry.sha256
    assert manifest["output_format"] == "wav"


def test_source_export_preserves_flac_bytes_and_reports_separate_digests(
    monkeypatch, tmp_path: Path
) -> None:
    payload = b"fLaC exact pinned source bytes"
    source = tmp_path / "source.flac"
    source.write_bytes(payload)
    entry = _entry(source, "flac", payload)
    monkeypatch.setattr(cli, "_catalog", lambda _paths: Catalog([entry]))
    output = tmp_path / "voice.flac"

    result = CliRunner().invoke(
        cli.app,
        ["export", str(entry.ref), "--output", str(output), "--format", "source"],
    )

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == payload
    manifest = json.loads((tmp_path / "voice.flac.voicefolio.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["source_sha256"] == entry.sha256
    assert manifest["source_format"] == "flac"
    assert manifest["output_format"] == "flac"
    assert "materialization" not in manifest


def test_source_export_rejects_misleading_extension(monkeypatch, tmp_path: Path) -> None:
    payload = b"source bytes"
    source = tmp_path / "source.flac"
    source.write_bytes(payload)
    entry = _entry(source, "flac", payload)
    monkeypatch.setattr(cli, "_catalog", lambda _paths: Catalog([entry]))

    result = CliRunner().invoke(
        cli.app,
        [
            "export",
            str(entry.ref),
            "--output",
            str(tmp_path / "voice.wav"),
            "--format",
            "source",
        ],
    )

    assert result.exit_code == 2
    assert "requires a .flac suffix" in result.output


def test_renderer_wav_export_materializes_flac_with_truthful_sidecar(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.flac"
    samples = np.array([0, 100, -100, 32767, -32768], dtype=np.int16)
    sf.write(source, samples, 24_000, format="FLAC", subtype="PCM_16")
    payload = source.read_bytes()
    entry = _entry(source, "flac", payload)
    monkeypatch.setattr(cli, "_catalog", lambda _paths: Catalog([entry]))
    output = tmp_path / "renderer.wav"

    result = CliRunner().invoke(
        cli.app,
        ["export", str(entry.ref), "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads(
        (tmp_path / "renderer.wav.voicefolio.json").read_text(encoding="utf-8")
    )
    assert manifest["source_sha256"] == entry.sha256
    assert manifest["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert manifest["sha256"] != manifest["source_sha256"]
    assert manifest["source_format"] == "flac"
    assert manifest["output_format"] == "wav"
    assert manifest["materialization"]["recipe"] == "flac-to-wav-v1"
    assert manifest["materialization"]["sample_rate"] == 24_000
    assert manifest["materialization"]["channels"] == 1
    assert manifest["materialization"]["subtype"] == "PCM_16"
