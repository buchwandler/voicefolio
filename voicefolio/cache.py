from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Literal
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


def default_cache_dir() -> Path:
    override = os.environ.get("VOICEFOLIO_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "voicefolio"


def asset_path(entry: VoiceEntry, cache_dir: str | Path | None = None) -> Path:
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
    return root / "assets" / "sha256" / entry.sha256[:2] / f"{entry.sha256}.wav"


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
    """Fetch and verify a pinned WAV, optionally reporting cache/download progress."""
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
                with urllib.request.urlopen(entry.url, timeout=60) as response:
                    length_header = response.headers.get("Content-Length")
                    try:
                        total = int(length_header) if length_header is not None else None
                    except ValueError:
                        total = None
                    if total is not None and total < 0:
                        total = None
                    completed = 0
                    _notify(progress, entry, "download", completed=completed, total=total)
                    while chunk := response.read(64 * 1024):
                        tmp.write(chunk)
                        completed += len(chunk)
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
