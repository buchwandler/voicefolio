from __future__ import annotations

import base64
import hashlib
import json
import re
import webbrowser
from collections import Counter
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .cache import fetch
from .catalog import Catalog
from .errors import AssetNotFoundError, VoicefolioError, VoiceNotFoundError
from .linked_assets import fetch_linked_asset
from .materialize import materialize_wav
from .models import VoiceEntry

_AUDIO_MIME = {"wav": "audio/wav", "flac": "audio/flac"}


def _csp_for_page(page: bytes) -> str:
    text = page.decode("utf-8")

    def hashes(tag: str) -> str:
        blocks = re.findall(
            rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}\s*>", text, flags=re.IGNORECASE | re.DOTALL
        )
        return (
            " ".join(
                "'sha256-"
                + base64.b64encode(hashlib.sha256(block.encode("utf-8")).digest()).decode(
                    "ascii"
                )
                + "'"
                for block in blocks
            )
            or "'none'"
        )

    return "; ".join(
        (
            "default-src 'none'",
            f"script-src {hashes('script')}",
            f"style-src {hashes('style')}",
            "connect-src 'self'",
            "media-src 'self' blob:",
            "img-src 'self' data:",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
        )
    )


def _facet_rows(entries: Sequence[VoiceEntry], getter: Any) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for entry in entries:
        value = getter(entry)
        if isinstance(value, str) and value:
            counts[value] += 1
    return [{"value": value, "count": count} for value, count in sorted(counts.items())]


def _voice_json(entry: VoiceEntry) -> dict[str, Any]:
    metadata = entry.metadata
    demo = metadata.get("preview_demo")
    return {
        "ref": str(entry.ref),
        "dataset": entry.dataset,
        "namespace": entry.ref.namespace,
        "language": entry.language,
        "variant": entry.variant,
        "license": entry.license,
        "format": entry.format,
        "speaker": metadata.get("speaker_name")
        if isinstance(metadata.get("speaker_name"), str)
        else None,
        "speaker_id": metadata.get("speaker_id")
        if isinstance(metadata.get("speaker_id"), str)
        else None,
        "gender": metadata.get("gender") if isinstance(metadata.get("gender"), str) else None,
        "pitch_band": metadata.get("pitch_band")
        if isinstance(metadata.get("pitch_band"), str)
        else None,
        "emotion": metadata.get("emotion")
        if isinstance(metadata.get("emotion"), str)
        else None,
        "preview_demo": isinstance(demo, Mapping),
    }


def _pagination(params: dict[str, list[str]]) -> tuple[int, int] | None:
    raw_limit = _first(params, "limit")
    raw_offset = _first(params, "offset")
    if raw_limit is None and raw_offset is None:
        return None
    try:
        limit = 100 if raw_limit is None else int(raw_limit)
        offset = 0 if raw_offset is None else int(raw_offset)
    except ValueError as exc:
        raise ValueError("limit and offset must be integers") from exc
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    return limit, offset


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
    content_security_policy = _csp_for_page(page)

    class VoicefolioHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            if parsed.path == "/":
                self._send_bytes(200, page, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/languages":
                entries = catalog.list()
                labels = {"en": "English", "fr": "French", "und": "Unknown"}
                counts = Counter(entry.language for entry in entries)
                self._send_json(
                    200,
                    [
                        {
                            "value": language,
                            "label": labels.get(language, language),
                            "count": count,
                        }
                        for language, count in sorted(counts.items())
                    ],
                )
                return
            if parsed.path in {"/api/sources", "/api/facets"}:
                entries = catalog.list()
                self._send_json(
                    200,
                    {
                        "namespaces": _facet_rows(entries, lambda entry: entry.ref.namespace),
                        "datasets": _facet_rows(entries, lambda entry: entry.dataset),
                        "languages": _facet_rows(entries, lambda entry: entry.language),
                        "licenses": _facet_rows(entries, lambda entry: entry.license),
                        "variants": _facet_rows(entries, lambda entry: entry.variant),
                        "genders": _facet_rows(
                            entries, lambda entry: entry.metadata.get("gender")
                        ),
                        "pitch_bands": _facet_rows(
                            entries, lambda entry: entry.metadata.get("pitch_band")
                        ),
                        "emotions": _facet_rows(
                            entries, lambda entry: entry.metadata.get("emotion")
                        ),
                    },
                )
                return
            if parsed.path == "/api/voices":
                try:
                    entries = catalog.list(
                        namespace=_first(params, "namespace"),
                        dataset=_first(params, "dataset"),
                        language=_first(params, "language"),
                        license=_first(params, "license"),
                        variant=_first(params, "variant"),
                        query=_first(params, "query"),
                        speaker=_first(params, "speaker"),
                        gender=_first(params, "gender"),
                        pitch_band=_first(params, "pitch_band"),
                        emotion=_first(params, "emotion"),
                    )
                    page_params = _pagination(params)
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                total = len(entries)
                if page_params is not None:
                    limit, offset = page_params
                    entries = entries[offset : offset + limit]
                self._send_json(
                    200,
                    [_voice_json(entry) for entry in entries],
                    total_count=total if page_params is not None else None,
                )
                return
            if parsed.path == "/api/audio":
                ref = _first(params, "ref")
                if not ref:
                    self._send_json(400, {"error": "ref is required"})
                    return
                asset = _first(params, "asset")
                renderer = _first(params, "renderer")
                if asset not in {None, "preview_demo"}:
                    self._send_json(400, {"error": "unsupported linked audio asset"})
                    return
                if renderer not in {None, "wav"} or (
                    asset is not None and renderer is not None
                ):
                    self._send_json(400, {"error": "renderer must be an explicit WAV request"})
                    return
                self._send_audio(ref, asset=asset, renderer=renderer)
                return
            self._send_json(404, {"error": "not found"})

        def _send_audio(self, ref: str, *, asset: str | None, renderer: str | None) -> None:
            try:
                entry = catalog.get(ref)
                if asset is not None:
                    resolved_asset = fetch_linked_asset(
                        entry, asset, cache_dir=cache_dir, offline=offline
                    )
                    audio_path = resolved_asset.path
                    audio_format = resolved_asset.asset.format
                else:
                    if renderer == "wav":
                        resolved = materialize_wav(entry, cache_dir=cache_dir, offline=offline)
                        audio_format = "wav"
                    else:
                        resolved = fetch(entry, cache_dir=cache_dir, offline=offline)
                        audio_format = entry.format
                    audio_path = resolved.path
                self._send_audio_file(audio_path, _AUDIO_MIME[audio_format])
            except (AssetNotFoundError, VoiceNotFoundError) as exc:
                self._send_json(404, {"error": str(exc)})
            except VoicefolioError as exc:
                self._send_json(503, {"error": str(exc)})
            except OSError as exc:
                self._send_json(500, {"error": f"cannot read cached audio: {exc}"})

        def _send_audio_file(self, path: Path, content_type: str) -> None:
            with path.open("rb") as audio:
                size = path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self._security_headers()
                self.end_headers()
                while chunk := audio.read(64 * 1024):
                    self.wfile.write(chunk)

        def _send_json(
            self, status: int, payload: Any, *, total_count: int | None = None
        ) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            if total_count is not None:
                self.send_header("X-Total-Count", str(total_count))
            self._security_headers()
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(payload)

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", content_security_policy)

        def version_string(self) -> str:
            return "Voicefolio"

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
