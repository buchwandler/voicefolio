from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from voicefolio import cli
from voicefolio.models import DownloadError, IntegrityError, OfflineError, PlaybackError

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
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert result.output.strip() == f"ok: {len(raw['voices'])} voices"


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


@pytest.mark.parametrize(
    ("error_type", "message", "options"),
    [
        (OfflineError, "voice is not cached", ["--offline"]),
        (DownloadError, "network unavailable", []),
        (IntegrityError, "SHA-256 mismatch", []),
    ],
)
def test_fetch_voicefolio_errors_are_concise(
    monkeypatch, error_type, message: str, options: list[str]
) -> None:
    def fail_fetch(*args, **kwargs):
        raise error_type(message)

    monkeypatch.setattr(cli, "fetch", fail_fetch)
    result = CliRunner().invoke(cli.app, ["fetch", REF, *options])

    assert result.exit_code == 1
    assert f"Error: {message}" in result.output
    assert "Traceback" not in result.output


def test_unknown_voice_error_is_concise() -> None:
    result = CliRunner().invoke(cli.app, ["show", "kyutai-tts-voices:does-not-exist"])

    assert result.exit_code == 1
    assert "Error: voice 'kyutai-tts-voices:does-not-exist' is not in the active catalog" in result.output
    assert "Traceback" not in result.output


def test_malformed_catalog_error_is_concise(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["list", "--catalog", str(malformed)])

    assert result.exit_code == 1
    assert "Error: cannot read catalog" in result.output
    assert "Traceback" not in result.output



def _browse_entries():
    return tuple(
        SimpleNamespace(
            ref=f"demo:{name}", license="CC0-1.0", variant="original", dataset="demo"
        )
        for name in ("voice-1", "voice-2", "voice-3")
    )


def _browse_catalog(entries):
    def list_voices(*, dataset, license, variant, query):
        rows = entries
        if dataset:
            rows = tuple(entry for entry in rows if entry.dataset == dataset)
        if license:
            rows = tuple(entry for entry in rows if entry.license == license)
        if variant:
            rows = tuple(entry for entry in rows if entry.variant == variant)
        if query:
            rows = tuple(entry for entry in rows if query.lower() in str(entry.ref).lower())
        return rows

    return SimpleNamespace(list=list_voices)


def test_browse_pages_searches_and_quits(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_catalog", lambda paths: _browse_catalog(_browse_entries()))

    result = CliRunner().invoke(
        cli.app,
        ["browse", "--page-size", "2"],
        input="n\np\n/\nvoice-3\nq\n",
    )

    assert result.exit_code == 0, result.output
    assert "Page 2/2" in result.output
    assert "Voicefolio — 1 voices" in result.output
    assert "demo:voice-3" in result.output


def test_browse_number_fetches_and_plays_selected_voice(monkeypatch, tmp_path: Path) -> None:
    entries = _browse_entries()
    monkeypatch.setattr(cli, "_catalog", lambda paths: _browse_catalog(entries))
    fetch_calls = []
    play_calls = []
    cached = tmp_path / "voice.wav"

    def fake_fetch(entry, *, cache_dir, offline):
        fetch_calls.append((entry, cache_dir, offline))
        return SimpleNamespace(path=cached)

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(
        cli, "play_wav", lambda path, *, device: play_calls.append((path, device))
    )
    result = CliRunner().invoke(
        cli.app,
        ["browse", "--page-size", "3", "--cache-dir", str(tmp_path), "--device", "2"],
        input="2\nq\n",
    )

    assert result.exit_code == 0, result.output
    assert fetch_calls == [(entries[1], tmp_path, False)]
    assert play_calls == [(cached, 2)]


def test_browse_recovers_from_offline_cache_miss(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_catalog", lambda paths: _browse_catalog(_browse_entries()))
    play_calls = []

    def fail_fetch(*args, **kwargs):
        raise OfflineError("voice is not cached")

    monkeypatch.setattr(cli, "fetch", fail_fetch)
    monkeypatch.setattr(
        cli, "play_wav", lambda *args, **kwargs: play_calls.append(args)
    )
    result = CliRunner().invoke(cli.app, ["browse"], input="1\nq\n")

    assert result.exit_code == 0, result.output
    assert "Error: voice is not cached" in result.output
    assert result.output.count("Voicefolio —") == 2
    assert not play_calls


def test_browse_recovers_when_optional_playback_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_catalog", lambda paths: _browse_catalog(_browse_entries()))
    monkeypatch.setattr(
        cli,
        "fetch",
        lambda *args, **kwargs: SimpleNamespace(path=tmp_path / "voice.wav"),
    )

    def fail_playback(path, *, device):
        raise PlaybackError("Install voicefolio[playback] for native preview.")

    monkeypatch.setattr(cli, "play_wav", fail_playback)
    result = CliRunner().invoke(cli.app, ["browse"], input="1\nq\n")

    assert result.exit_code == 0, result.output
    assert "Error: Install voicefolio[playback]" in result.output
    assert result.output.count("Voicefolio —") == 2



def test_browse_web_command_passes_local_server_options(monkeypatch, tmp_path: Path) -> None:
    catalog = object()
    calls = []
    catalog_path = tmp_path / "extra.json"
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cli, "_catalog", lambda paths: catalog)
    monkeypatch.setattr(
        cli,
        "serve_browser",
        lambda actual, **options: calls.append((actual, options)),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "browse-web",
            "--catalog",
            str(catalog_path),
            "--cache-dir",
            str(cache_dir),
            "--offline",
            "--port",
            "8765",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (catalog, {"cache_dir": cache_dir, "offline": True, "port": 8765})
    ]
