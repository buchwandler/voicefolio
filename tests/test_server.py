from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen

from voicefolio import server
from voicefolio.catalog import Catalog
from voicefolio.models import VoiceEntry, VoiceRef


def _entry(voice_id: str, digest: str) -> VoiceEntry:
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
    )


@contextmanager
def _running_server(catalog: Catalog) -> Iterator[str]:
    httpd = HTTPServer(("127.0.0.1", 0), server._handler_for(catalog, cache_dir=None, offline=False))
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
            _entry("dataset/alpha", "a" * 64),
            _entry("dataset/beta", "b" * 64),
        ]
    )
    with _running_server(catalog) as base_url:
        with urlopen(f"{base_url}/") as response:
            page = response.read().decode("utf-8")
            assert response.headers["Content-Type"].startswith("text/html")
        with urlopen(f"{base_url}/api/voices?query=alpha") as response:
            voices = json.loads(response.read())

    assert "<audio id=\"player\"" in page
    assert len(voices) == 1
    assert voices[0]["ref"] == "demo:dataset/alpha"


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
