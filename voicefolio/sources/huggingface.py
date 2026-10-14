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

USER_AGENT = "voicefolio/0.1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _quote_repository(repository: str) -> str:
    if not repository or any(not part for part in repository.split("/")):
        raise CatalogError("Hugging Face repository must be a non-empty owner/name path")
    return "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            if not isinstance(payload, bytes):
                raise CatalogError("Hugging Face response body must be bytes")
            return payload
    except (OSError, urllib.error.URLError) as exc:
        raise CatalogError(f"Unable to fetch Hugging Face resource {url}") from exc


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
    """Return all repository tree entries for an exact revision, following pagination."""
    repo = _quote_repository(repository)
    rev = urllib.parse.quote(revision, safe="")
    url = f"https://huggingface.co/api/datasets/{repo}/tree/{rev}?recursive=true&expand=true"
    entries: list[dict[str, Any]] = []
    while url:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
                link_header = response.headers.get("Link", "")
        except (OSError, urllib.error.URLError) as exc:
            raise CatalogError(f"Unable to fetch repository tree for {revision}") from exc
        try:
            page = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CatalogError("Hugging Face repository tree is not valid UTF-8 JSON") from exc
        if not isinstance(page, list):
            raise CatalogError("Hugging Face repository tree response must be an array")
        entries.extend(item for item in page if isinstance(item, dict))
        next_link = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        url = next_link.group(1) if next_link else ""
    return entries


def resolve_url(repository: str, revision: str, path: str) -> str:
    """Build a revision-pinned Hugging Face download URL."""
    repo = _quote_repository(repository)
    rev = urllib.parse.quote(revision, safe="")
    asset = urllib.parse.quote(path, safe="/")
    return f"https://huggingface.co/{repo}/resolve/{rev}/{asset}?download=true"


def blob_url(repository: str, revision: str, path: str) -> str:
    """Build a revision-pinned Hugging Face browser URL."""
    repo = _quote_repository(repository)
    rev = urllib.parse.quote(revision, safe="")
    asset = urllib.parse.quote(path, safe="/")
    return f"https://huggingface.co/{repo}/blob/{rev}/{asset}"


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


def file_integrity(
    repository: str,
    revision: str,
    path: str,
    tree_metadata: Mapping[str, Any],
) -> tuple[int, str]:
    """Return positive file size and lowercase SHA-256 using tree metadata when possible."""
    lfs = tree_metadata.get("lfs")
    lfs_size = lfs.get("size") if isinstance(lfs, Mapping) else None
    size = _positive_int(tree_metadata.get("size")) or _positive_int(lfs_size)
    sha256 = _sha256_from_tree(tree_metadata)
    if size is not None and sha256 is not None:
        return size, sha256

    payload = _read_url(resolve_url(repository, revision, path))
    actual_size = len(payload)
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if size is not None and size != actual_size:
        raise CatalogError(
            f"{path}: tree metadata size {size} does not match downloaded size {actual_size}"
        )
    if sha256 is not None and sha256 != actual_sha256:
        raise CatalogError(f"{path}: tree metadata SHA-256 does not match downloaded bytes")
    if actual_size <= 0:
        raise CatalogError(f"{path}: upstream WAV must have positive size")
    return actual_size, actual_sha256
