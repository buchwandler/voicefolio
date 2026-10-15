"""Bounded, revision-pinned GitHub access for maintained source catalogs."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from ..errors import CatalogError

USER_AGENT = "voicefolio/0.2"
MAX_METADATA_BYTES = 1024 * 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_TREE_ENTRIES = 200_000
MAX_AUDIO_BYTES = 128 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class _HttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise CatalogError("GitHub source redirected to a non-HTTPS URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _repository(repository: str) -> str:
    if (
        not isinstance(repository, str)
        or _REPOSITORY_RE.fullmatch(repository) is None
        or any(part in {".", ".."} for part in repository.split("/"))
    ):
        raise CatalogError("GitHub repository must be a safe owner/name path")
    return "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))


def _path(path: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        raise CatalogError("GitHub source path must be a non-empty safe slash path")
    decoded = path
    for _ in range(2):
        decoded = urllib.parse.unquote(decoded)
    if (
        decoded.startswith("/")
        or re.match(r"^[A-Za-z]:", decoded)
        or any(part in {"", ".", ".."} for part in decoded.split("/"))
        or any(ord(character) < 32 for character in decoded)
    ):
        raise CatalogError(f"unsafe GitHub source path {path!r}")
    return path


def _commit(revision: str) -> str:
    if not isinstance(revision, str) or _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("GitHub content URLs require an exact 40-character commit SHA")
    return revision


def _open_url(url: str, *, timeout: int = 60) -> Any:
    if urllib.parse.urlsplit(url).scheme.lower() != "https":
        raise CatalogError("GitHub source URLs must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_HttpsRedirectHandler())
    try:
        response = opener.open(request, timeout=timeout)
    except CatalogError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise CatalogError(f"Unable to fetch GitHub source URL {url}") from exc
    final_url = response.geturl()
    if urllib.parse.urlsplit(final_url).scheme.lower() != "https":
        response.close()
        raise CatalogError("GitHub source response used a non-HTTPS URL")
    return response


def _read_url(url: str, *, max_bytes: int) -> bytes:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    with _open_url(url) as response:
        header_size = response.headers.get("Content-Length")
        if header_size is not None:
            try:
                if int(header_size) > max_bytes:
                    raise CatalogError(f"GitHub resource exceeds {max_bytes} bytes")
            except ValueError as exc:
                raise CatalogError("GitHub response has an invalid Content-Length") from exc
        payload = response.read(max_bytes + 1)
    if not isinstance(payload, bytes):
        raise CatalogError("GitHub response body must be bytes")
    if len(payload) > max_bytes:
        raise CatalogError(f"GitHub resource exceeds {max_bytes} bytes")
    return payload


def _json_url(url: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Any:
    payload = _read_url(url, max_bytes=max_bytes)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError("GitHub metadata is not valid UTF-8 JSON") from exc


def resolve_revision(repository: str, revision: str) -> str:
    """Resolve a branch, tag, or commit-ish to a lowercase full commit SHA."""
    repo = _repository(repository)
    if not isinstance(revision, str) or not revision.strip() or len(revision) > 256:
        raise CatalogError("GitHub revision must be a non-empty bounded string")
    reference = urllib.parse.quote(revision, safe="")
    data = _json_url(f"https://api.github.com/repos/{repo}/commits/{reference}")
    resolved = data.get("sha") if isinstance(data, Mapping) else None
    if not isinstance(resolved, str) or _SHA_RE.fullmatch(resolved.lower()) is None:
        raise CatalogError("GitHub revision did not resolve to a full 40-character commit SHA")
    return resolved.lower()


def repository_tree(repository: str, commit: str) -> list[dict[str, Any]]:
    """Return a complete recursive tree, refusing GitHub's truncated response."""
    repo = _repository(repository)
    pin = _commit(commit)
    data = _json_url(
        f"https://api.github.com/repos/{repo}/git/trees/{pin}?recursive=1",
        max_bytes=MAX_TREE_BYTES,
    )
    if not isinstance(data, Mapping):
        raise CatalogError("GitHub recursive tree response must be an object")
    if data.get("truncated") is not False:
        raise CatalogError("GitHub recursive tree is truncated or has no truncation status")
    entries = data.get("tree")
    if not isinstance(entries, list) or len(entries) > MAX_TREE_ENTRIES:
        raise CatalogError("GitHub recursive tree is missing or exceeds the entry limit")
    if any(not isinstance(entry, Mapping) for entry in entries):
        raise CatalogError("GitHub recursive tree contains a malformed entry")
    return [dict(entry) for entry in entries]


def raw_url(repository: str, commit: str, path: str) -> str:
    """Return an HTTPS raw-content URL pinned to an exact commit."""
    repo = _repository(repository)
    pin = _commit(commit)
    source_path = urllib.parse.quote(_path(path), safe="/")
    return f"https://raw.githubusercontent.com/{repo}/{pin}/{source_path}"


def blob_url(repository: str, commit: str, path: str) -> str:
    """Return a human-readable GitHub file URL pinned to an exact commit."""
    repo = _repository(repository)
    pin = _commit(commit)
    source_path = urllib.parse.quote(_path(path), safe="/")
    return f"https://github.com/{repo}/blob/{pin}/{source_path}"


def read_file(
    repository: str,
    commit: str,
    path: str,
    *,
    max_bytes: int = MAX_METADATA_BYTES,
) -> bytes:
    """Read one metadata file from a pinned revision with a strict size bound."""
    return _read_url(raw_url(repository, commit, path), max_bytes=max_bytes)


def file_integrity(
    repository: str,
    commit: str,
    path: str,
    *,
    expected_size: int | None = None,
    expected_blob_id: str | None = None,
    max_bytes: int = MAX_AUDIO_BYTES,
) -> tuple[int, str]:
    """Stream a pinned file and return its exact byte count and SHA-256 digest."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if expected_size is not None and (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or expected_size > max_bytes
    ):
        raise CatalogError("GitHub tree file size is invalid or exceeds the audio limit")
    if expected_blob_id is not None and (
        expected_size is None or _SHA_RE.fullmatch(expected_blob_id) is None
    ):
        raise CatalogError(
            "GitHub tree blob identity requires a valid size and 40-character SHA"
        )
    url = raw_url(repository, commit, path)
    digest = hashlib.sha256()
    git_digest = hashlib.sha1()
    if expected_blob_id is not None and expected_size is not None:
        git_digest.update(f"blob {expected_size}\0".encode("ascii"))
    size = 0
    with _open_url(url) as response:
        header_size = response.headers.get("Content-Length")
        if header_size is not None:
            try:
                announced = int(header_size)
            except ValueError as exc:
                raise CatalogError("GitHub response has an invalid Content-Length") from exc
            if announced > max_bytes or (
                expected_size is not None and announced != expected_size
            ):
                raise CatalogError(
                    f"GitHub file size differs from its pinned tree entry: {path}"
                )
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes or (expected_size is not None and size > expected_size):
                raise CatalogError(f"GitHub file exceeds its pinned size limit: {path}")
            digest.update(chunk)
            git_digest.update(chunk)
    if size <= 0 or (expected_size is not None and size != expected_size):
        raise CatalogError(f"GitHub file size differs from its pinned tree entry: {path}")
    if expected_blob_id is not None and git_digest.hexdigest() != expected_blob_id:
        raise CatalogError(f"GitHub bytes do not match the pinned Git blob id: {path}")
    result = digest.hexdigest()
    if _SHA256_RE.fullmatch(result) is None:
        raise CatalogError(f"failed to calculate GitHub file SHA-256: {path}")
    return size, result
