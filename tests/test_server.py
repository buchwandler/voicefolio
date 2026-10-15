from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen

from voicefolio import server
from voicefolio.catalog import Catalog
from voicefolio.models import VoiceEntry, VoiceRef


def _entry(voice_id: str, digest: str, language: str = "und") -> VoiceEntry:
    return VoiceEntry(
        ref=VoiceRef("demo", voice_id),
        dataset=voice_id.split("/", 1)[0],
        variant="original",
        format="wav",
        url=f"https://example.invalid/{voice_id}.wav",
        size=1,
        sha256=digest,
        source_repository="example/voices",
        source_revision="a" * 40,
        source_path=f"{voice_id}.wav",
        license="CC0-1.0",
        language=language,
    )


@contextmanager
def _running_server(catalog: Catalog) -> Iterator[str]:
    httpd = HTTPServer(
        ("127.0.0.1", 0), server._handler_for(catalog, cache_dir=None, offline=False)
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def test_browser_page_and_voice_filters_are_served_locally() -> None:
    catalog = Catalog(
        [
            _entry("dataset/alpha", "a" * 64, language="en"),
            _entry("dataset/beta", "b" * 64, language="fr"),
            _entry("dataset/gamma", "c" * 64, language="und"),
        ]
    )
    with _running_server(catalog) as base_url:
        with urlopen(f"{base_url}/") as response:
            page = response.read().decode("utf-8")
            assert response.headers["Content-Type"].startswith("text/html")
            csp = response.headers["Content-Security-Policy"]
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urlopen(f"{base_url}/api/voices?query=alpha") as response:
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Cache-Control"] == "no-store"
            voices = json.loads(response.read())
        with urlopen(f"{base_url}/api/voices?language=en") as response:
            english = json.loads(response.read())
        with urlopen(f"{base_url}/api/voices?query=alpha&language=en") as response:
            combined = json.loads(response.read())
        with urlopen(f"{base_url}/api/voices?query=beta&language=en") as response:
            no_match = json.loads(response.read())
        with urlopen(f"{base_url}/api/languages") as response:
            languages = json.loads(response.read())

    assert '<audio id="player"' in page
    assert '<select name="language" id="language">' in page
    assert "'unsafe-inline'" not in csp
    assert "'sha256-" in csp
    assert "innerHTML" not in page
    assert 'name="namespace"' in page
    assert 'name="pitch_band"' in page
    assert 'textContent = "Synthesized demo"' in page
    assert 'fetch("/api/languages")' in page
    assert len(voices) == 1
    assert voices[0]["ref"] == "demo:dataset/alpha"
    assert voices[0]["language"] == "en"
    assert [voice["language"] for voice in english] == ["en"]
    assert [voice["ref"] for voice in combined] == ["demo:dataset/alpha"]
    assert no_match == []
    assert languages == [
        {"value": "en", "label": "English", "count": 1},
        {"value": "fr", "label": "French", "count": 1},
        {"value": "und", "label": "Unknown", "count": 1},
    ]


def test_browser_facets_filters_pagination_and_total_count() -> None:
    entries = [
        replace(
            _entry("dataset/alpha", "a" * 64, language="en"),
            metadata={
                "speaker_name": "Alice Example",
                "gender": "female",
                "pitch_band": "low",
                "emotion": "calm",
            },
        ),
        replace(
            _entry("dataset/beta", "b" * 64, language="en"),
            metadata={
                "speaker_name": "Bob Example",
                "gender": "male",
                "pitch_band": "high",
                "emotion": "happy",
            },
        ),
        replace(
            _entry("dataset/gamma", "c" * 64, language="fr"),
            metadata={
                "speaker_name": "Cora Example",
                "gender": "female",
                "pitch_band": "low",
                "emotion": "calm",
            },
        ),
    ]
    with _running_server(Catalog(entries)) as base_url:
        with urlopen(f"{base_url}/api/sources") as response:
            facets = json.loads(response.read())
        with urlopen(f"{base_url}/api/voices?gender=female&limit=1&offset=0") as response:
            voices = json.loads(response.read())
            total_count = response.headers["X-Total-Count"]
        with urlopen(f"{base_url}/api/voices?speaker=Bob&limit=5") as response:
            speakers = json.loads(response.read())

    assert {row["value"] for row in facets["namespaces"]} == {"demo"}
    assert {row["value"] for row in facets["genders"]} == {"female", "male"}
    assert {row["value"] for row in facets["emotions"]} == {"calm", "happy"}
    assert len(voices) == 1
    assert voices[0]["speaker"] == "Alice Example"
    assert voices[0]["pitch_band"] == "low"
    assert total_count == "2"
    assert [voice["speaker"] for voice in speakers] == ["Bob Example"]


def test_browser_audio_formats_and_linked_demo_are_explicit(
    monkeypatch, tmp_path: Path
) -> None:
    entry = replace(
        _entry("dataset/alpha", "a" * 64),
        format="flac",
        url="https://example.invalid/dataset/alpha.flac",
    )
    catalog = Catalog([entry])
    flac_path = tmp_path / "alpha.flac"
    flac_path.write_bytes(b"source flac")
    wav_path = tmp_path / "alpha-rendered.wav"
    wav_path.write_bytes(b"renderer wav")
    demo_path = tmp_path / "demo.wav"
    demo_path.write_bytes(b"verified demo")
    monkeypatch.setattr(
        server, "fetch", lambda *args, **kwargs: SimpleNamespace(path=flac_path)
    )
    monkeypatch.setattr(
        server,
        "materialize_wav",
        lambda *args, **kwargs: SimpleNamespace(path=wav_path),
    )
    monkeypatch.setattr(
        server,
        "fetch_linked_asset",
        lambda *args, **kwargs: SimpleNamespace(
            path=demo_path, asset=SimpleNamespace(format="wav")
        ),
    )

    with _running_server(catalog) as base_url:
        with urlopen(f"{base_url}/api/audio?ref={quote(str(entry.ref))}") as response:
            source_bytes = response.read()
            source_type = response.headers["Content-Type"]
        with urlopen(
            f"{base_url}/api/audio?ref={quote(str(entry.ref))}&renderer=wav"
        ) as response:
            renderer_bytes = response.read()
            renderer_type = response.headers["Content-Type"]
        with urlopen(
            f"{base_url}/api/audio?ref={quote(str(entry.ref))}&asset=preview_demo"
        ) as response:
            demo_bytes = response.read()

    assert source_bytes == b"source flac"
    assert source_type == "audio/flac"
    assert renderer_bytes == b"renderer wav"
    assert renderer_type == "audio/wav"
    assert demo_bytes == b"verified demo"


def test_browser_audio_route_uses_verified_fetch(monkeypatch, tmp_path: Path) -> None:
    entry = _entry("dataset/alpha", "a" * 64)
    catalog = Catalog([entry])
    audio_path = tmp_path / "alpha.wav"
    audio_path.write_bytes(b"verified wav")
    fetch_calls = []

    def fake_fetch(actual_entry, *, cache_dir, offline):
        fetch_calls.append((actual_entry, cache_dir, offline))
        return SimpleNamespace(path=audio_path)

    monkeypatch.setattr(server, "fetch", fake_fetch)
    with (
        _running_server(catalog) as base_url,
        urlopen(f"{base_url}/api/audio?ref={quote(str(entry.ref))}") as response,
    ):
        payload = response.read()
        assert response.headers["Content-Type"] == "audio/wav"

    assert payload == b"verified wav"
    assert fetch_calls == [(entry, None, False)]


def test_browser_server_binds_loopback_opens_page_and_closes(monkeypatch) -> None:
    calls = {}

    class FakeServer:
        server_port = 8765

        def __init__(self, address, handler):
            calls["address"] = address
            calls["handler"] = handler

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            calls["closed"] = True

    opened = []
    monkeypatch.setattr(server, "HTTPServer", FakeServer)
    monkeypatch.setattr(server.webbrowser, "open", opened.append)

    server.serve_browser(Catalog(), port=8765)

    assert calls["address"] == ("127.0.0.1", 8765)
    assert calls["closed"] is True
    assert opened == ["http://127.0.0.1:8765/"]
