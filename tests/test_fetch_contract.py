from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voicefolio.cache import (
    MAX_SOURCE_ASSET_BYTES,
    _BoundedHTTPSRedirectHandler,
    asset_path,
    fetch,
)
from voicefolio.models import (
    AccessError,
    AssetNotFoundError,
    DownloadError,
    FetchProgress,
    IntegrityError,
    OfflineError,
    VoiceEntry,
    VoiceRef,
)


def _entry(source: Path, payload: bytes) -> VoiceEntry:
    return VoiceEntry(
        ref=VoiceRef.parse("test:voice"),
        dataset="test",
        variant="original",
        format="wav",
        url=source.resolve().as_uri(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source_repository="local/test",
        source_revision="rev1",
        source_path="voice.wav",
        license="CC0-1.0",
    )


def test_fetch_reports_chunked_progress_and_cached_phases(tmp_path: Path) -> None:
    payload = b"RIFF" + b"x" * (160 * 1024)
    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)
    events: list[FetchProgress] = []
    resolved = fetch(entry, cache_dir=tmp_path / "cache", progress=events.append)

    assert resolved.path.read_bytes() == payload
    phases = [event.phase for event in events]
    assert phases[0] == "cache_check"
    assert phases[-1] == "ready"
    assert "verify" in phases
    download = [event for event in events if event.phase == "download"]
    assert len(download) > 1
    completed = [event.completed for event in download]
    assert completed == sorted(completed)
    assert completed[-1] == len(payload)
    assert download[-1].total == len(payload)

    cached_events: list[FetchProgress] = []
    with patch("voicefolio.cache._open_url") as urlopen:
        fetch(entry, cache_dir=tmp_path / "cache", progress=cached_events.append)
    urlopen.assert_not_called()
    assert [event.phase for event in cached_events] == ["cache_check", "verify", "ready"]


def test_offline_cache_miss_has_typed_error_and_cache_check_event(tmp_path: Path) -> None:
    payload = b"wav"
    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)
    events: list[FetchProgress] = []
    with pytest.raises(OfflineError):
        fetch(entry, cache_dir=tmp_path / "empty-cache", offline=True, progress=events.append)
    assert [event.phase for event in events] == ["cache_check"]


def test_corrupt_cache_is_integrity_error_without_network(tmp_path: Path) -> None:
    payload = b"expected bytes"
    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)
    cached = asset_path(entry, tmp_path / "cache")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"bad")
    with (
        patch("voicefolio.cache._open_url") as urlopen,
        pytest.raises(IntegrityError),
    ):
        fetch(entry, cache_dir=tmp_path / "cache")
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, AccessError), (403, AccessError), (404, AssetNotFoundError), (500, DownloadError)],
)
def test_http_statuses_map_to_typed_fetch_errors(
    tmp_path: Path, status: int, error_type: type[DownloadError]
) -> None:
    entry = _entry(tmp_path / "unused.wav", b"asset")
    error = urllib.error.HTTPError(entry.url, status, "request failed", {}, io.BytesIO())
    with (
        patch("voicefolio.cache._open_url", side_effect=error),
        pytest.raises(error_type),
    ):
        fetch(entry, cache_dir=tmp_path / f"cache-{status}")


def test_transport_failure_is_download_error(tmp_path: Path) -> None:
    entry = _entry(tmp_path / "unused.wav", b"asset")
    with (
        patch(
            "voicefolio.cache._open_url",
            side_effect=urllib.error.URLError("connection refused"),
        ),
        pytest.raises(DownloadError, match="unable to download"),
    ):
        fetch(entry, cache_dir=tmp_path / "cache")


def test_unsupported_scheme_is_download_error(tmp_path: Path) -> None:
    entry = _entry(tmp_path / "unused.wav", b"asset")
    changed = VoiceEntry(
        ref=entry.ref,
        dataset=entry.dataset,
        variant=entry.variant,
        format=entry.format,
        url="ftp://example.invalid/voice.wav",
        size=entry.size,
        sha256=entry.sha256,
        source_repository=entry.source_repository,
        source_revision=entry.source_revision,
        source_path=entry.source_path,
        license=entry.license,
    )
    with pytest.raises(DownloadError, match="unsupported catalog URL scheme"):
        fetch(changed, cache_dir=tmp_path / "cache")


def test_flac_source_fetch_uses_flac_suffix_and_preserves_bytes(tmp_path: Path) -> None:
    payload = b"fLaC" + b"source FLAC fixture"
    source = tmp_path / "source.flac"
    source.write_bytes(payload)
    entry = replace(_entry(source, payload), format="flac", source_path="voice.flac")

    resolved = fetch(entry, cache_dir=tmp_path / "cache")

    assert resolved.path.suffix == ".flac"
    assert resolved.path.name == f"{entry.sha256}.flac"
    assert resolved.path.read_bytes() == payload
    assert resolved.sha256 == entry.sha256


def test_oversized_stream_is_rejected_before_cache_commit(tmp_path: Path) -> None:
    payload = b"abc"
    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)

    response = MagicMock()
    response.headers = {}
    response.__enter__.return_value = response
    response.read.side_effect = [b"abcd", b""]

    destination = asset_path(entry, tmp_path / "cache")
    with (
        patch("voicefolio.cache._open_url", return_value=response),
        pytest.raises(IntegrityError, match="exceeds pinned size"),
    ):
        fetch(entry, cache_dir=tmp_path / "cache")

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_source_asset_size_limit_rejects_oversized_catalog_pin(tmp_path: Path) -> None:
    entry = replace(
        _entry(tmp_path / "unused.wav", b"asset"),
        size=MAX_SOURCE_ASSET_BYTES + 1,
    )
    with (
        patch("voicefolio.cache._open_url") as open_url,
        pytest.raises(DownloadError, match="exceeds"),
    ):
        fetch(entry, cache_dir=tmp_path / "cache")
    open_url.assert_not_called()


def test_source_redirect_policy_is_bounded_and_https_only() -> None:
    handler = _BoundedHTTPSRedirectHandler()
    request = urllib.request.Request("https://source.example/audio.wav")
    assert handler.max_redirections == 5
    with pytest.raises(urllib.error.HTTPError, match="redirect target must be an HTTPS"):
        handler.redirect_request(
            request,
            io.BytesIO(),
            302,
            "Found",
            {},
            "http://unsafe.example/audio.wav",
        )
