from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from voicefolio import cli
from voicefolio.models import PlaybackError

REF = "kyutai-tts-voices:voice-zero/peter_yearsley"


def test_preview_fetches_prints_and_plays_native(monkeypatch, tmp_path: Path) -> None:
    entry = object()
    cached_path = tmp_path / "cache" / "voice.wav"
    fetch_calls = []
    play_calls = []

    monkeypatch.setattr(cli, "_catalog", lambda paths: SimpleNamespace(get=lambda ref: entry))

    def fake_fetch(actual_entry, *, cache_dir, offline):
        fetch_calls.append((actual_entry, cache_dir, offline))
        return SimpleNamespace(path=cached_path)

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(
        cli,
        "play_wav",
        lambda path, *, device: play_calls.append((path, device)),
    )

    result = CliRunner().invoke(
        cli.app,
        ["preview", REF, "--device", "3", "--cache-dir", str(tmp_path / "cache"), "--offline"],
    )

    assert result.exit_code == 0, result.output
    assert str(cached_path) in result.output
    assert fetch_calls == [(entry, tmp_path / "cache", True)]
    assert play_calls == [(cached_path, 3)]
    assert not hasattr(cli, "webbrowser")


def test_preview_reports_playback_errors_without_traceback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli, "_catalog", lambda paths: SimpleNamespace(get=lambda ref: object())
    )
    monkeypatch.setattr(
        cli,
        "fetch",
        lambda *args, **kwargs: SimpleNamespace(path=tmp_path / "voice.wav"),
    )

    def fail_playback(path, *, device):
        raise PlaybackError("PortAudio unavailable")

    monkeypatch.setattr(cli, "play_wav", fail_playback)
    result = CliRunner().invoke(cli.app, ["preview", REF])

    assert result.exit_code == 1
    assert "Error: PortAudio unavailable" in result.output
    assert "Traceback" not in result.output


def test_catalog_verify_accepts_packaged_catalog() -> None:
    catalog_path = Path("voicefolio/resources/catalogs/kyutai-tts-voices.json")
    result = CliRunner().invoke(cli.app, ["catalog", "verify", str(catalog_path)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "ok: 1161 voices"


def test_catalog_build_uses_packaged_previous_catalog_by_default(
    monkeypatch, tmp_path: Path
) -> None:
    packaged = Path("voicefolio/resources/catalogs/kyutai-tts-voices.json")
    output = tmp_path / "candidate.json"
    calls = []

    def fake_build(previous, *, repository, revision):
        calls.append((previous, repository, revision))
        return json.loads(packaged.read_text(encoding="utf-8"))

    monkeypatch.setattr(cli, "_builtin_kyutai_catalog_path", lambda: packaged)
    monkeypatch.setattr(cli, "build_kyutai_catalog", fake_build)
    monkeypatch.setattr(cli, "verify_kyutai_catalog", lambda catalog: None)
    result = CliRunner().invoke(cli.app, ["catalog", "build-kyutai", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert calls == [(packaged, "kyutai/tts-voices", "main")]
    assert json.loads(output.read_text(encoding="utf-8"))["namespace"] == ("kyutai-tts-voices")
