from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from ..models import CatalogError

USER_AGENT = "voicefolio/0.2"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_TREE_PAGE_BYTES = 16 * 1024 * 1024
MAX_TREE_PAGES = 10_000
MAX_TREE_ENTRIES = 200_000
MAX_AUDIO_BYTES = 128 * 1024 * 1024
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


def _quote_repository(repository: str) -> str:
    parts = repository.split("/") if isinstance(repository, str) else []
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise CatalogError("Hugging Face repository must be an owner/name path")
    return "/".join(urllib.parse.quote(part, safe="") for part in parts)


def _validate_path(path: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        raise CatalogError("source path must be a non-empty safe slash path")
    decoded = urllib.parse.unquote(urllib.parse.unquote(path))
    if (
        decoded.startswith("/")
        or re.match(r"^[A-Za-z]:", decoded)
        or any(part in {"", ".", ".."} for part in decoded.split("/"))
    ):
        raise CatalogError(f"unsafe source path {path!r}")
    return path


def _read_url(url: str, *, max_bytes: int = MAX_METADATA_BYTES) -> bytes:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read(max_bytes + 1)
            if not isinstance(payload, bytes):
                raise CatalogError("Hugging Face response body must be bytes")
            if len(payload) > max_bytes:
                raise CatalogError(f"Hugging Face resource exceeds {max_bytes} bytes: {url}")
            return payload
    except CatalogError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise CatalogError(f"Unable to fetch Hugging Face resource {url}") from exc


def read_file(
    repository: str,
    revision: str,
    path: str,
    *,
    max_bytes: int = MAX_METADATA_BYTES,
) -> bytes:
    """Read one safely addressed, revision-pinned source file within a size bound."""
    return _read_url(raw_url(repository, revision, path), max_bytes=max_bytes)


def raw_url(repository: str, revision: str, path: str) -> str:
    """Build a pinned raw-content URL for a Hugging Face dataset file."""
    repo = _quote_repository(repository)
    if not isinstance(revision, str) or _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Hugging Face raw URLs require an exact 40-character commit SHA")
    asset = urllib.parse.quote(_validate_path(path), safe="/")
    return f"https://huggingface.co/datasets/{repo}/raw/{revision}/{asset}"


def resolve_revision(repository: str, revision: str) -> str:
    """Resolve a dataset branch or tag to its exact lowercase commit SHA."""
    repo = _quote_repository(repository)
    rev = urllib.parse.quote(revision, safe="")
    payload = _read_url(f"https://huggingface.co/api/datasets/{repo}/revision/{rev}")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError("Hugging Face revision metadata is not valid UTF-8 JSON") from exc
    resolved = data.get("sha") if isinstance(data, Mapping) else None
    if not isinstance(resolved, str) or _SHA_RE.fullmatch(resolved.lower()) is None:
        raise CatalogError("Unable to resolve an exact 40-character dataset commit SHA")
    return resolved.lower()


def repository_tree(repository: str, revision: str) -> list[dict[str, Any]]:
    """Return every nested tree entry for an exact revision, following bounded pages."""
    repo = _quote_repository(repository)
    rev = urllib.parse.quote(revision, safe="")
    pending_dirs = [""]
    visited_dirs: set[str] = set()
    entries: dict[str, dict[str, Any]] = {}
    page_count = 0

    while pending_dirs:
        directory = pending_dirs.pop(0)
        if directory in visited_dirs:
            continue
        visited_dirs.add(directory)
        path_suffix = (
            f"/{urllib.parse.quote(_validate_path(directory), safe='/')}" if directory else ""
        )
        url = (
            f"https://huggingface.co/api/datasets/{repo}/tree/{rev}{path_suffix}"
            "?recursive=true&expand=true"
        )
        expected_path = urllib.parse.urlsplit(url).path
        while url:
            page_count += 1
            if page_count > MAX_TREE_PAGES:
                raise CatalogError("Hugging Face repository tree exceeds the page limit")
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = response.read(MAX_TREE_PAGE_BYTES + 1)
                    link_header = response.headers.get("Link", "")
                if len(payload) > MAX_TREE_PAGE_BYTES:
                    raise CatalogError(
                        f"Hugging Face tree page exceeds {MAX_TREE_PAGE_BYTES} bytes"
                    )
            except CatalogError:
                raise
            except (OSError, urllib.error.URLError) as exc:
                raise CatalogError(f"Unable to fetch repository tree for {revision}") from exc
            try:
                page = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CatalogError(
                    "Hugging Face repository tree is not valid UTF-8 JSON"
                ) from exc
            if not isinstance(page, list):
                raise CatalogError("Hugging Face repository tree response must be an array")
            for item in page:
                if not isinstance(item, dict):
                    raise CatalogError(
                        "Hugging Face repository tree contains a malformed entry"
                    )
                item_path = item.get("path")
                if not isinstance(item_path, str):
                    raise CatalogError("Hugging Face repository tree entry has no path")
                _validate_path(item_path)
                if item.get("type") not in {"file", "directory"}:
                    raise CatalogError(
                        f"Hugging Face tree entry has unsupported type: {item_path!r}"
                    )
                prior = entries.get(item_path)
                prior = entries.get(item_path)
                if prior is not None:
                    identity_fields = ("type", "path", "oid", "size", "lfs", "xetHash")
                    for field in identity_fields:
                        if field in prior and field in item and prior[field] != item[field]:
                            raise CatalogError(
                                f"Hugging Face tree entry changed across pages: {item_path!r}"
                            )
                    entries[item_path] = {**prior, **item}
                else:
                    entries[item_path] = item
                if item.get("type") == "directory":
                    pending_dirs.append(item_path)
                if len(entries) > MAX_TREE_ENTRIES:
                    raise CatalogError("Hugging Face repository tree exceeds the entry limit")

            next_link = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if next_link is None:
                url = ""
                continue
            next_url = urllib.parse.urljoin(url, next_link.group(1))
            parsed_next = urllib.parse.urlsplit(next_url)
            if (
                parsed_next.scheme != "https"
                or parsed_next.netloc != "huggingface.co"
                or parsed_next.path != expected_path
            ):
                raise CatalogError("Hugging Face tree pagination link is not same-origin")
            url = next_url

    return [entries[path] for path in sorted(entries)]


def resolve_url(repository: str, revision: str, path: str) -> str:
    """Build a safe, revision-pinned Hugging Face download URL."""
    repo = _quote_repository(repository)
    if _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Hugging Face asset URLs require an exact 40-character commit SHA")
    asset = urllib.parse.quote(_validate_path(path), safe="/")
    return f"https://huggingface.co/{repo}/resolve/{revision}/{asset}?download=true"


def dataset_resolve_url(repository: str, revision: str, path: str) -> str:
    """Build a dataset-typed, revision-pinned Hugging Face download URL."""
    repo = _quote_repository(repository)
    if not isinstance(revision, str) or _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Hugging Face dataset URLs require an exact 40-character commit SHA")
    asset = urllib.parse.quote(_validate_path(path), safe="/")
    return f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{asset}?download=true"


def blob_url(repository: str, revision: str, path: str) -> str:
    """Build a safe, revision-pinned Hugging Face browser URL."""
    repo = _quote_repository(repository)
    if _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Hugging Face asset URLs require an exact 40-character commit SHA")
    asset = urllib.parse.quote(_validate_path(path), safe="/")
    return f"https://huggingface.co/{repo}/blob/{revision}/{asset}"


def dataset_blob_url(repository: str, revision: str, path: str) -> str:
    """Build a dataset-typed, revision-pinned Hugging Face browser URL."""
    repo = _quote_repository(repository)
    if not isinstance(revision, str) or _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Hugging Face dataset URLs require an exact 40-character commit SHA")
    asset = urllib.parse.quote(_validate_path(path), safe="/")
    return f"https://huggingface.co/datasets/{repo}/blob/{revision}/{asset}"


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _sha256_from_tree(metadata: Mapping[str, Any]) -> str | None:
    lfs = metadata.get("lfs")
    if not isinstance(lfs, Mapping):
        return None
    oid = lfs.get("oid")
    if not isinstance(oid, str):
        return None
    if oid.startswith("sha256:"):
        oid = oid.removeprefix("sha256:")
    oid = oid.lower()
    return oid if _SHA256_RE.fullmatch(oid) is not None else None


def _stream_url_integrity(url: str, *, max_bytes: int = MAX_AUDIO_BYTES) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            while chunk := response.read(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise CatalogError(
                        f"source audio exceeds the {max_bytes}-byte limit: {url}"
                    )
                digest.update(chunk)
                if len(prefix) < len(_LFS_POINTER):
                    prefix.extend(chunk[: len(_LFS_POINTER) - len(prefix)])
    except CatalogError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise CatalogError(f"Unable to stream source audio {url}") from exc
    if bytes(prefix).startswith(_LFS_POINTER):
        raise CatalogError(f"{url} returned a Git LFS pointer instead of audio bytes")
    if size <= 0:
        raise CatalogError(f"{url} is empty; source audio must have positive size")
    return size, digest.hexdigest()


def file_integrity(
    repository: str,
    revision: str,
    path: str,
    tree_metadata: Mapping[str, Any],
    *,
    dataset: bool = False,
) -> tuple[int, str]:
    """Return positive source size and SHA-256, streaming bytes only when needed."""
    lfs = tree_metadata.get("lfs")
    lfs_size = _positive_int(lfs.get("size")) if isinstance(lfs, Mapping) else None
    tree_size = _positive_int(tree_metadata.get("size"))
    if lfs_size is not None and tree_size is not None and lfs_size != tree_size:
        raise CatalogError(f"{path}: Git LFS and tree sizes disagree")
    size = lfs_size or tree_size
    sha256 = _sha256_from_tree(tree_metadata)
    if size is not None and sha256 is not None:
        return size, sha256
    if size is not None and size > MAX_AUDIO_BYTES:
        raise CatalogError(f"{path}: source audio exceeds the {MAX_AUDIO_BYTES}-byte limit")

    url_builder = dataset_resolve_url if dataset else resolve_url
    actual_size, actual_sha256 = _stream_url_integrity(
        url_builder(repository, revision, path),
        max_bytes=MAX_AUDIO_BYTES,
    )
    if size is not None and size != actual_size:
        raise CatalogError(
            f"{path}: tree metadata size {size} does not match downloaded size {actual_size}"
        )
    if sha256 is not None and sha256 != actual_sha256:
        raise CatalogError(f"{path}: tree metadata SHA-256 does not match source bytes")
    return actual_size, actual_sha256
