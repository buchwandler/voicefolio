"""Typed metadata assets and their verified content-addressed cache access."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from .cache import _open_url, default_cache_dir
from .errors import (
    AccessError,
    AssetNotFoundError,
    CatalogError,
    DownloadError,
    IntegrityError,
    OfflineError,
)
from .models import VoiceEntry

_SHA256_LENGTH = 64
_FORMATS = frozenset({"wav", "flac"})
MAX_LINKED_ASSET_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PinnedLinkedAsset:
    kind: str
    format: str
    url: str
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise CatalogError("linked asset kind must be a non-empty string")
        if not isinstance(self.format, str) or self.format.lower() not in _FORMATS:
            raise CatalogError(f"unsupported linked asset format {self.format!r}")
        object.__setattr__(self, "format", self.format.lower())
        if not isinstance(self.url, str) or not self.url.strip():
            raise CatalogError("linked asset URL must be a non-empty string")
        if (
            not isinstance(self.path, str)
            or not self.path
            or "\\" in self.path
            or "\x00" in self.path
        ):
            raise CatalogError("linked asset path must be a safe relative slash path")
        decoded = unquote(unquote(self.path))
        path_parts = decoded.split("/")
        if decoded.startswith("/") or any(part in {"", ".", ".."} for part in path_parts):
            raise CatalogError("linked asset path must not contain traversal components")
        suffix = PurePosixPath(self.path).suffix.lower().lstrip(".")
        if suffix != self.format:
            raise CatalogError("linked asset path extension must match its format")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size <= 0:
            raise CatalogError("linked asset size must be a positive integer")
        if self.size > MAX_LINKED_ASSET_BYTES:
            raise CatalogError(f"linked asset exceeds the {MAX_LINKED_ASSET_BYTES}-byte limit")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != _SHA256_LENGTH
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise CatalogError(
                "linked asset SHA-256 must be 64 lowercase hexadecimal characters"
            )

    @classmethod
    def from_entry(cls, entry: VoiceEntry, name: str) -> PinnedLinkedAsset:
        if not isinstance(name, str) or not name:
            raise CatalogError("linked asset name must be a non-empty string")
        raw = entry.metadata.get(name)
        if not isinstance(raw, Mapping):
            raise AssetNotFoundError(f"{entry.ref} has no linked asset {name!r}")
        try:
            kind = raw["kind"]
            audio_format = raw["format"]
            url = raw["url"]
            path = raw["path"]
            size = raw["size"]
            sha256 = raw["sha256"]
        except KeyError as exc:
            raise CatalogError(
                f"linked asset {name!r} for {entry.ref} is missing {exc.args[0]!r}"
            ) from exc
        if not all(isinstance(value, str) for value in (kind, audio_format, url, path, sha256)):
            raise CatalogError(
                f"linked asset {name!r} for {entry.ref} has invalid string fields"
            )
        return cls(kind, audio_format, url, path, size, sha256)


@dataclass(frozen=True, slots=True)
class ResolvedLinkedAsset:
    asset: PinnedLinkedAsset
    path: Path


def linked_asset_path(
    asset: PinnedLinkedAsset,
    cache_dir: str | Path | None = None,
) -> Path:
    """Return a format-preserving content-addressed path for a linked asset."""
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
    return root / "assets" / "sha256" / asset.sha256[:2] / f"{asset.sha256}.{asset.format}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_linked_asset(path: Path, asset: PinnedLinkedAsset) -> None:
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise IntegrityError(f"cannot inspect linked asset {path}: {exc}") from exc
    if actual_size != asset.size:
        raise IntegrityError(
            f"linked asset size mismatch for {asset.path}: expected {asset.size}, found {actual_size}"
        )
    try:
        actual_sha256 = _sha256_file(path)
    except OSError as exc:
        raise IntegrityError(f"cannot read linked asset {path}: {exc}") from exc
    if actual_sha256 != asset.sha256:
        raise IntegrityError(
            f"linked asset SHA-256 mismatch for {asset.path}: "
            f"expected {asset.sha256}, found {actual_sha256}"
        )


def _validate_url(asset: PinnedLinkedAsset) -> None:
    parsed = urlparse(asset.url)
    if parsed.scheme not in {"https", "file"}:
        raise DownloadError(f"unsupported linked asset URL scheme {parsed.scheme!r}")
    if parsed.scheme == "https" and (not parsed.hostname or parsed.username or parsed.password):
        raise DownloadError(
            "linked asset HTTPS URL must have a host and no embedded credentials"
        )


def fetch_linked_asset(
    entry: VoiceEntry,
    name: str,
    *,
    cache_dir: str | Path | None = None,
    offline: bool = False,
) -> ResolvedLinkedAsset:
    """Fetch a linked metadata asset with size/hash verification and atomic caching."""
    asset = PinnedLinkedAsset.from_entry(entry, name)
    destination = linked_asset_path(asset, cache_dir)
    if destination.exists():
        verify_linked_asset(destination, asset)
        return ResolvedLinkedAsset(asset=asset, path=destination)
    if offline:
        raise OfflineError(
            f"linked asset {name!r} for {entry.ref} is not cached and offline mode is enabled"
        )
    _validate_url(asset)

    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                with _open_url(asset.url, timeout=60) as response:
                    length_header = response.headers.get("Content-Length")
                    if length_header is not None:
                        try:
                            content_length = int(length_header)
                        except ValueError:
                            content_length = None
                        if content_length is not None and content_length != asset.size:
                            raise IntegrityError(
                                f"linked asset size mismatch for {asset.path}: "
                                f"expected {asset.size}, response declared {content_length}"
                            )
                    downloaded = 0
                    while chunk := response.read(64 * 1024):
                        downloaded += len(chunk)
                        if downloaded > asset.size:
                            raise IntegrityError(
                                f"linked asset {asset.path} exceeds pinned size {asset.size}"
                            )
                        output.write(chunk)
            except urllib.error.HTTPError as exc:
                message = (
                    f"HTTP {exc.code} while fetching linked asset {name!r} for {entry.ref}"
                )
                if exc.code in {401, 403}:
                    raise AccessError(message) from exc
                if exc.code == 404:
                    raise AssetNotFoundError(message) from exc
                raise DownloadError(message) from exc
            except FileNotFoundError as exc:
                raise AssetNotFoundError(
                    f"linked asset {name!r} for {entry.ref} was not found at its pinned URL"
                ) from exc
            except IntegrityError:
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                raise DownloadError(
                    f"unable to download linked asset {name!r} for {entry.ref}: {exc}"
                ) from exc

        verify_linked_asset(temporary, asset)
        os.replace(temporary, destination)
        return ResolvedLinkedAsset(asset=asset, path=destination)
    except (AccessError, AssetNotFoundError, DownloadError, IntegrityError):
        raise
    except OSError as exc:
        raise DownloadError(
            f"unable to cache linked asset {name!r} for {entry.ref}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
