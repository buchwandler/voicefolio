from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .cache import fetch
from .catalog import Catalog
from .models import VoicefolioError, VoiceNotFoundError


def _handler_for(
    catalog: Catalog, *, cache_dir: Path | None, offline: bool
) -> type[BaseHTTPRequestHandler]:
    page = (
        files("voicefolio")
        .joinpath("resources")
        .joinpath("web")
        .joinpath("index.html")
        .read_bytes()
    )

    class VoicefolioHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            if parsed.path == "/":
                self._send_bytes(200, page, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/voices":
                entries = catalog.list(
                    dataset=_first(params, "dataset"),
                    license=_first(params, "license"),
                    variant=_first(params, "variant"),
                    query=_first(params, "query"),
                )
                self._send_json(
                    200,
                    [
                        {
                            "ref": str(entry.ref),
                            "dataset": entry.dataset,
                            "variant": entry.variant,
                            "license": entry.license,
                        }
                        for entry in entries
                    ],
                )
                return
            if parsed.path == "/api/audio":
                ref = _first(params, "ref")
                if not ref:
                    self._send_json(400, {"error": "ref is required"})
                    return
                self._send_audio(ref)
                return
            self._send_json(404, {"error": "not found"})

        def _send_audio(self, ref: str) -> None:
            try:
                resolved = fetch(catalog.get(ref), cache_dir=cache_dir, offline=offline)
                size = resolved.path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with resolved.path.open("rb") as audio:
                    while chunk := audio.read(64 * 1024):
                        self.wfile.write(chunk)
            except VoiceNotFoundError as exc:
                self._send_json(404, {"error": str(exc)})
            except VoicefolioError as exc:
                self._send_json(503, {"error": str(exc)})
            except OSError as exc:
                self._send_json(500, {"error": f"cannot read cached audio: {exc}"})

        def _send_json(self, status: int, payload: Any) -> None:
            self._send_bytes(
                status,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return VoicefolioHandler


def _first(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None


def serve_browser(
    catalog: Catalog,
    *,
    cache_dir: Path | None = None,
    offline: bool = False,
    port: int = 0,
) -> None:
    """Serve the packaged browser UI on loopback until interrupted."""
    server = HTTPServer(
        ("127.0.0.1", port),
        _handler_for(catalog, cache_dir=cache_dir, offline=offline),
    )
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Voicefolio browser: {url} (press Ctrl-C to stop)", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
