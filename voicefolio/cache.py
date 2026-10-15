from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from .models import (
    AccessError,
    AssetNotFoundError,
    DownloadError,
    FetchProgress,
    IntegrityError,
    OfflineError,
    ResolvedVoice,
    VoiceEntry,
)

_SOURCE_SUFFIXES = {"wav": ".wav", "flac": ".flac"}
_MAX_REDIRECTIONS = 5
MAX_SOURCE_ASSET_BYTES = 512 * 1024 * 1024


class _BoundedHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = _MAX_REDIRECTIONS
    max_repeats = 3

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = urlparse(newurl)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username
            or target.password
        ):
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                "redirect target must be an HTTPS URL without embedded credentials",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_url(url: str, *, timeout: float) -> Any:
    """Open source URLs with bounded HTTPS-only redirects."""
    return urllib.request.build_opener(_BoundedHTTPSRedirectHandler()).open(
        url, timeout=timeout
    )


def default_cache_dir() -> Path:
    override = os.environ.get("VOICEFOLIO_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "voicefolio"


def asset_path(entry: VoiceEntry, cache_dir: str | Path | None = None) -> Path:
    suffix = _SOURCE_SUFFIXES.get(entry.format)
    if suffix is None:
        raise DownloadError(f"unsupported source format {entry.format!r} for {entry.ref}")
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
    return root / "assets" / "sha256" / entry.sha256[:2] / f"{entry.sha256}{suffix}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, entry: VoiceEntry) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IntegrityError(f"cannot inspect {path}: {exc}") from exc
    if size != entry.size:
        raise IntegrityError(
            f"size mismatch for {entry.ref}: expected {entry.size}, found {size}"
        )
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise IntegrityError(f"cannot read {path}: {exc}") from exc
    if digest != entry.sha256:
        raise IntegrityError(
            f"SHA-256 mismatch for {entry.ref}: expected {entry.sha256}, found {digest}"
        )


def _notify(
    progress: Callable[[FetchProgress], None] | None,
    entry: VoiceEntry,
    phase: Literal["cache_check", "download", "verify", "ready"],
    *,
    completed: int | None = None,
    total: int | None = None,
) -> None:
    if progress is not None:
        progress(
            FetchProgress(phase=phase, ref=str(entry.ref), completed=completed, total=total)
        )


def _http_error(exc: urllib.error.HTTPError, entry: VoiceEntry) -> DownloadError:
    message = f"HTTP {exc.code} while fetching {entry.ref} from {entry.url}"
    if exc.code in {401, 403}:
        return AccessError(message)
    if exc.code == 404:
        return AssetNotFoundError(message)
    return DownloadError(message)


def fetch(
    entry: VoiceEntry,
    *,
    cache_dir: str | Path | None = None,
    offline: bool = False,
    progress: Callable[[FetchProgress], None] | None = None,
) -> ResolvedVoice:
    """Fetch and verify exact source bytes, optionally reporting cache/download progress."""
    if entry.size > MAX_SOURCE_ASSET_BYTES:
        raise DownloadError(
            f"source asset for {entry.ref} exceeds {MAX_SOURCE_ASSET_BYTES} bytes"
        )
    _notify(progress, entry, "cache_check")
    destination = asset_path(entry, cache_dir)
    if destination.exists():
        _notify(progress, entry, "verify", total=entry.size)
        verify_file(destination, entry)
        _notify(progress, entry, "ready", completed=entry.size, total=entry.size)
        return ResolvedVoice(entry=entry, path=destination)
    if offline:
        raise OfflineError(f"voice {entry.ref} is not cached and offline mode is enabled")

    scheme = urlparse(entry.url).scheme
    if scheme not in {"https", "file"}:
        raise DownloadError(f"unsupported catalog URL scheme {scheme!r} for {entry.ref}")

    tmp_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                with _open_url(entry.url, timeout=60) as response:
                    length_header = response.headers.get("Content-Length")
                    try:
                        declared_size = (
                            int(length_header) if length_header is not None else None
                        )
                    except ValueError:
                        declared_size = None
                    if declared_size is not None and declared_size != entry.size:
                        raise IntegrityError(
                            f"size mismatch for {entry.ref}: expected {entry.size}, "
                            f"response declared {declared_size}"
                        )
                    total = entry.size
                    completed = 0
                    _notify(progress, entry, "download", completed=completed, total=total)
                    while chunk := response.read(64 * 1024):
                        next_completed = completed + len(chunk)
                        if next_completed > entry.size:
                            raise IntegrityError(
                                f"download for {entry.ref} exceeds pinned size {entry.size}"
                            )
                        tmp.write(chunk)
                        completed = next_completed
                        _notify(
                            progress,
                            entry,
                            "download",
                            completed=completed,
                            total=total,
                        )
            except urllib.error.HTTPError as exc:
                raise _http_error(exc, entry) from exc
            except FileNotFoundError as exc:
                raise AssetNotFoundError(
                    f"asset for {entry.ref} was not found at its pinned URL"
                ) from exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                raise DownloadError(f"unable to download {entry.ref}: {exc}") from exc

        _notify(progress, entry, "verify", total=entry.size)
        verify_file(tmp_path, entry)
        os.replace(tmp_path, destination)
        _notify(progress, entry, "ready", completed=entry.size, total=entry.size)
        return ResolvedVoice(entry=entry, path=destination)
    except (DownloadError, IntegrityError):
        raise
    except OSError as exc:
        raise DownloadError(f"unable to cache {entry.ref}: {exc}") from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
