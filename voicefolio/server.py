from __future__ import annotations

import json
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .cache import fetch
from .catalog import Catalog
from .models import VoicefolioError


def serve_catalog(
    catalog: Catalog,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    cache_dir: str | Path | None = None,
    open_browser: bool = True,
) -> None:
    html = (
        files("voicefolio")
        .joinpath("resources", "web", "index.html")
        .read_text(encoding="utf-8")
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self._send(HTTPStatus.OK, html.encode(), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/voices":
                rows = [entry.to_dict() for entry in catalog.list()]
                self._send(
                    HTTPStatus.OK,
                    json.dumps(rows).encode(),
                    "application/json; charset=utf-8",
                )
                return
            if parsed.path == "/api/audio":
                query = urllib.parse.parse_qs(parsed.query)
                ref = query.get("ref", [""])[0]
                try:
                    entry = catalog.get(ref)
                    resolved = fetch(entry, cache_dir=cache_dir)
                    body = resolved.path.read_bytes()
                except (OSError, ValueError, VoicefolioError) as exc:
                    self._send(
                        HTTPStatus.BAD_REQUEST,
                        json.dumps({"error": str(exc)}).encode(),
                        "application/json; charset=utf-8",
                    )
                    return
                self._send(HTTPStatus.OK, body, "audio/wav")
                return
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}/"
    print(f"Voicefolio catalog: {url}")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
