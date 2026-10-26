"""Maintainer builder and verifier for the pinned Voice-Zero FLAC catalog."""

from __future__ import annotations

import copy
import html
import json
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..errors import CatalogError
from .base import merge_immutable_rows
from .github import (
    blob_url,
    file_integrity,
    raw_url,
    read_file,
    repository_tree,
    resolve_revision,
)

NAMESPACE = "voice-zero"
DEFAULT_REPOSITORY = "OwenTyme/voice-zero"
DEFAULT_REVISION = "main"
_LICENSE = "CC0-1.0"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.'-]+(?:/[A-Za-z0-9_.'-]+)*$")
_EMOTION_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.'-]+\.flac$")
_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]*)\)$")
_OVERRIDE_RESOURCE = "voice-zero-overrides.json"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogError(f"Voice-Zero {label} must be an object")
    return value


def _safe_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or any(ord(character) < 32 or character.isspace() for character in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise CatalogError(f"Voice-Zero {label}: unsafe relative path")
    return value


def _https_url(value: Any, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise CatalogError(f"Voice-Zero {label} must be an HTTPS URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CatalogError(f"Voice-Zero {label} must be an HTTPS URL")
    return value


def load_overrides() -> dict[str, Any]:
    """Load the checked-in reviewed filename corrections and exclusions."""
    resource = (
        files("voicefolio")
        .joinpath("resources")
        .joinpath("sources")
        .joinpath(_OVERRIDE_RESOURCE)
    )
    try:
        with resource.open("r", encoding="utf-8") as handle:
            policy = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read Voice-Zero override policy: {exc}") from exc
    policy = _mapping(policy, "override policy")
    if policy.get("source_repository") != DEFAULT_REPOSITORY:
        raise CatalogError("Voice-Zero override policy has the wrong source repository")
    return dict(policy)


def _source_docs(repository: str, revision: str) -> dict[str, str]:
    paths = ("README.md", "LICENSE.md", "voices/README.md", "voices-emotion/README.md")
    docs: dict[str, str] = {}
    for path in paths:
        payload = read_file(repository, revision, path, max_bytes=1024 * 1024)
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogError(f"Voice-Zero evidence file {path} is not UTF-8") from exc
        if not text.strip():
            raise CatalogError(f"Voice-Zero evidence file {path} is empty")
        docs[path] = text

    for path in ("README.md", "LICENSE.md"):
        normalized = " ".join(docs[path].lower().split())
        if "cc0" not in normalized or "all files in this repository" not in normalized:
            raise CatalogError(
                f"Voice-Zero {path} does not assert CC0 coverage for all repository files"
            )
    if "file name" not in docs["voices/README.md"].lower():
        raise CatalogError("Voice-Zero voices README has no filename/source attribution table")
    emotion_doc = docs["voices-emotion/README.md"].lower()
    if "synthetic" not in emotion_doc or "voices" not in emotion_doc:
        raise CatalogError(
            "Voice-Zero emotion README does not document synthetic voice variants"
        )
    return docs


def _table_link(
    value: str, label: str, *, allow_empty_url: bool = False
) -> tuple[str, str | None]:
    match = _LINK_RE.fullmatch(value.strip())
    if match is None:
        raise CatalogError(
            f"Voice-Zero attribution {label} is not a conservative Markdown link"
        )
    text, url = html.unescape(match.group(1)).strip(), html.unescape(match.group(2)).strip()
    if not text:
        raise CatalogError(f"Voice-Zero attribution {label} has an empty label")
    if not url and allow_empty_url:
        return text, None
    return text, _https_url(url, f"attribution {label}")


def _parse_attribution(text: str) -> dict[str, dict[str, Any]]:
    """Parse only exact filename rows; malformed or duplicate claims fail closed."""
    result: dict[str, dict[str, Any]] = {}
    found_table = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.lstrip().startswith("|"):
            continue
        cells = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            raise CatalogError(
                f"Voice-Zero attribution table row {line_number} has {len(cells)} cells"
            )
        if cells[1].lower() == "file name" or re.fullmatch(r"[-:\s]+", cells[1]):
            found_table = True
            continue
        if not found_table:
            continue
        speaker_name, speaker_url = _table_link(
            cells[0], f"speaker on row {line_number}", allow_empty_url=True
        )
        accent = html.unescape(cells[2]).strip()
        if not accent:
            raise CatalogError(f"Voice-Zero attribution row {line_number} has no accent claim")
        source_title, source_url = _table_link(cells[3], f"source on row {line_number}")
        filenames = re.split(r"<br\s*/?>", cells[1], flags=re.IGNORECASE)
        if not filenames:
            raise CatalogError(f"Voice-Zero attribution row {line_number} has no filenames")
        for raw_filename in filenames:
            filename = html.unescape(raw_filename).strip()
            if _FILENAME_RE.fullmatch(filename) is None:
                raise CatalogError(
                    f"Voice-Zero attribution row {line_number} has unsafe filename {filename!r}"
                )
            if filename in result:
                raise CatalogError(f"Voice-Zero attribution repeats filename {filename!r}")
            result[filename] = {
                "speaker_name": speaker_name,
                "speaker_url": speaker_url,
                "accent": accent,
                "source_title": source_title,
                "source_url": source_url,
            }
    if not found_table or not result:
        raise CatalogError("Voice-Zero voices README contains no usable attribution table")
    return result


def _tree_index(repository: str, revision: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in repository_tree(repository, revision):
        path = item.get("path")
        if not isinstance(path, str):
            raise CatalogError("Voice-Zero tree entry has no path")
        _safe_path(path, "tree path")
        if path in index:
            raise CatalogError(f"Voice-Zero tree contains duplicate path {path!r}")
        if item.get("type") != "blob":
            continue
        index[path] = item
    return index


def _blob_info(item: Mapping[str, Any], path: str) -> tuple[int, str]:
    size = item.get("size")
    blob_id = item.get("sha")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise CatalogError(f"Voice-Zero tree entry {path} has an invalid byte size")
    if not isinstance(blob_id, str) or _SHA_RE.fullmatch(blob_id) is None:
        raise CatalogError(f"Voice-Zero tree entry {path} has an invalid Git blob id")
    return size, blob_id


def _previous_rows(
    previous_path: str | Path | None,
    *,
    bootstrap: bool,
    repository: str,
) -> list[Mapping[str, Any]]:
    if previous_path is None:
        if not bootstrap:
            raise CatalogError("first Voice-Zero build requires explicit bootstrap mode")
        return []
    path = Path(previous_path)
    if not path.exists():
        raise CatalogError(f"previous Voice-Zero catalog does not exist: {path}")
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read previous Voice-Zero catalog {path}: {exc}") from exc
    _mapping(previous, "previous catalog")
    verify_voice_zero_catalog(previous)
    if previous.get("source_repository") != repository:
        raise CatalogError("previous Voice-Zero catalog uses a different source repository")
    rows = previous.get("voices")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise CatalogError("previous Voice-Zero catalog voices must be an array of objects")
    return rows


def _override_tables(
    policy: Mapping[str, Any],
    *,
    repository: str,
    original_paths: set[str],
    attribution: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    aliases_raw = _mapping(policy.get("filename_aliases", {}), "filename aliases")
    exclusions_raw = _mapping(policy.get("exclude", {}), "exclusions")
    aliases: dict[str, tuple[str, str]] = {}
    used_alias_names: set[str] = set()
    for raw_path, raw_value in aliases_raw.items():
        path = _safe_path(raw_path, "filename alias path")
        value = _mapping(raw_value, f"filename alias for {path}")
        filename = value.get("attribution_filename")
        reason = value.get("reason")
        if path not in original_paths:
            raise CatalogError(f"Voice-Zero filename override targets missing path {path}")
        if (
            not isinstance(filename, str)
            or _FILENAME_RE.fullmatch(filename) is None
            or filename not in attribution
            or filename == Path(path).name
        ):
            raise CatalogError(
                f"Voice-Zero filename override for {path} is not an active mismatch"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise CatalogError(
                f"Voice-Zero filename override for {path} requires a review reason"
            )
        if filename in used_alias_names:
            raise CatalogError(f"Voice-Zero filename override repeats {filename!r}")
        used_alias_names.add(filename)
        aliases[path] = (filename, reason.strip())

    exclusions: dict[str, str] = {}
    for raw_path, raw_value in exclusions_raw.items():
        path = _safe_path(raw_path, "exclusion path")
        value = _mapping(raw_value, f"exclusion for {path}")
        reason = value.get("reason")
        if path not in original_paths:
            raise CatalogError(f"Voice-Zero exclusion targets missing path {path}")
        if Path(path).name in attribution:
            raise CatalogError(f"Voice-Zero exclusion for {path} is no longer ambiguous")
        if not isinstance(reason, str) or not reason.strip():
            raise CatalogError(f"Voice-Zero exclusion for {path} requires a diagnostic reason")
        exclusions[path] = reason.strip()

    matched: set[str] = set()
    for path in original_paths:
        if path in exclusions:
            continue
        filename = aliases[path][0] if path in aliases else Path(path).name
        if filename not in attribution:
            raise CatalogError(
                f"Voice-Zero original {path} has no exact attribution row or reviewed override"
            )
        matched.add(filename)
    stale = set(attribution) - matched
    if stale:
        raise CatalogError(
            "Voice-Zero attribution table has filenames not matched to source paths or overrides: "
            + ", ".join(sorted(stale)[:8])
        )
    return aliases, exclusions


def _needs_integrity(
    source_path: str,
    item: Mapping[str, Any],
    previous_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    voice_id = source_path.removesuffix(".flac")
    size, blob_id = _blob_info(item, source_path)
    previous = previous_by_id.get(voice_id)
    if previous is None:
        return True
    metadata = previous.get("metadata")
    return not (
        isinstance(metadata, Mapping)
        and metadata.get("source_blob_id") == blob_id
        and previous.get("size") == size
        and previous.get("source_path") == source_path
    )


def _integrity_for_paths(
    repository: str,
    revision: str,
    paths: list[str],
    tree: Mapping[str, Mapping[str, Any]],
    previous_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[int, str]]:
    pending_paths = [
        path for path in paths if _needs_integrity(path, tree[path], previous_by_id)
    ]
    results: dict[str, tuple[int, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                file_integrity,
                repository,
                revision,
                path,
                expected_size=_blob_info(tree[path], path)[0],
                expected_blob_id=_blob_info(tree[path], path)[1],
            ): path
            for path in pending_paths
        }
        for future, path in futures.items():
            try:
                results[path] = future.result()
            except Exception as exc:
                for unfinished in futures:
                    unfinished.cancel()
                raise CatalogError(
                    f"cannot verify Voice-Zero source file {path}: {exc}"
                ) from exc
    return results


def _row_for_file(
    *,
    repository: str,
    revision: str,
    source_path: str,
    item: Mapping[str, Any],
    variant: str,
    base_id: str | None,
    metadata: Mapping[str, Any],
    previous_by_id: Mapping[str, Mapping[str, Any]],
    integrity_by_path: Mapping[str, tuple[int, str]],
) -> dict[str, Any]:
    voice_id = source_path.removesuffix(".flac")
    size, blob_id = _blob_info(item, source_path)
    previous = previous_by_id.get(voice_id)
    if previous is not None:
        old_metadata = previous.get("metadata")
        if (
            isinstance(old_metadata, Mapping)
            and old_metadata.get("source_blob_id") == blob_id
            and previous.get("size") == size
            and previous.get("source_path") == source_path
        ):
            return copy.deepcopy(dict(previous))

    try:
        actual_size, digest = integrity_by_path[source_path]
    except KeyError as exc:
        raise CatalogError(f"missing streamed integrity result for {source_path}") from exc
    row_metadata = dict(metadata)
    row_metadata["source_blob_id"] = blob_id
    return {
        "id": voice_id,
        "dataset": NAMESPACE,
        "language": "en",
        "variant": variant,
        "base_id": base_id,
        "format": "flac",
        "url": raw_url(repository, revision, source_path),
        "size": actual_size,
        "sha256": digest,
        "source_repository": repository,
        "source_revision": revision,
        "source_path": source_path,
        "license": _LICENSE,
        "license_evidence": blob_url(repository, revision, "LICENSE.md"),
        "metadata": row_metadata,
    }


def build_catalog(
    previous_path: str | Path | None = None,
    *,
    repository: str = DEFAULT_REPOSITORY,
    revision: str = DEFAULT_REVISION,
    bootstrap: bool = False,
) -> dict[str, Any]:
    """Build a deterministic, append-only Voice-Zero catalog from a pinned Git tree."""
    if repository != DEFAULT_REPOSITORY:
        raise CatalogError(f"Voice-Zero repository must be {DEFAULT_REPOSITORY!r}")
    previous_rows = _previous_rows(
        previous_path,
        bootstrap=bootstrap,
        repository=repository,
    )
    pinned_revision = resolve_revision(repository, revision)
    if _SHA_RE.fullmatch(pinned_revision) is None:
        raise CatalogError("Voice-Zero revision did not resolve to a 40-character commit")
    previous_by_id = {str(row["id"]): row for row in previous_rows}
    policy = load_overrides()
    tree = _tree_index(repository, pinned_revision)
    required_docs = {"README.md", "LICENSE.md", "voices/README.md", "voices-emotion/README.md"}
    if not required_docs.issubset(tree):
        missing = sorted(required_docs - set(tree))
        raise CatalogError(f"Voice-Zero pinned tree is missing evidence files: {missing}")
    docs = _source_docs(repository, pinned_revision)
    attribution = _parse_attribution(docs["voices/README.md"])

    unexpected_voice_files = sorted(
        path
        for path in tree
        if (
            path.startswith("voices/")
            and path != "voices/README.md"
            and not path.endswith(".flac")
        )
        or (
            path.startswith("voices-emotion/")
            and path != "voices-emotion/README.md"
            and not path.endswith(".flac")
        )
    )
    if unexpected_voice_files:
        raise CatalogError(
            "Voice-Zero has unsupported files under audio directories: "
            + ", ".join(unexpected_voice_files[:8])
        )
    original_paths = {
        path for path in tree if path.startswith("voices/") and path.endswith(".flac")
    }
    if not original_paths:
        raise CatalogError("Voice-Zero pinned tree has no original FLAC files")
    aliases, exclusions = _override_tables(
        policy,
        repository=repository,
        original_paths=original_paths,
        attribution=attribution,
    )
    emotion_paths = sorted(
        path for path in tree if path.startswith("voices-emotion/") and path.endswith(".flac")
    )
    for path in original_paths:
        if path.count("/") != 1:
            raise CatalogError(f"Voice-Zero original path must be a single filename: {path}")
    for path in emotion_paths:
        parts = path.split("/")
        if len(parts) != 3 or _EMOTION_RE.fullmatch(parts[2].removesuffix(".flac")) is None:
            raise CatalogError(f"Voice-Zero emotion path/tag is unsafe: {path}")
        if f"voices/{parts[1]}.flac" not in original_paths:
            raise CatalogError(f"Voice-Zero emotion {path} has no exact original path")
    paths_to_pin = sorted(
        [path for path in original_paths if path not in exclusions]
        + [
            path
            for path in emotion_paths
            if f"voices/{path.split('/')[1]}.flac" not in exclusions
        ]
    )
    integrity_by_path = _integrity_for_paths(
        repository,
        pinned_revision,
        paths_to_pin,
        tree,
        previous_by_id,
    )

    evidence_common = [
        blob_url(repository, pinned_revision, "README.md"),
        blob_url(repository, pinned_revision, "LICENSE.md"),
        blob_url(repository, pinned_revision, "voices/README.md"),
    ]
    discovered: list[dict[str, Any]] = []
    quarantined: list[dict[str, str]] = []
    original_metadata: dict[str, dict[str, Any]] = {}
    for path in sorted(original_paths):
        item = tree[path]
        if path in exclusions:
            reason = exclusions[path]
            quarantined.append({"source_path": path, "reason": reason})
            original_metadata[path] = {}
            continue
        alias = aliases.get(path)
        attribution_name = alias[0] if alias is not None else Path(path).name
        source = attribution[attribution_name]
        speaker_id = Path(path).name.removesuffix(".flac")
        status = (
            "reviewed_filename_override" if alias is not None else "reviewed_exact_filename"
        )
        metadata: dict[str, Any] = {
            "speaker_id": speaker_id,
            "speaker_name": source["speaker_name"],
            "speaker_url": source["speaker_url"],
            "source_title": source["source_title"],
            "source_url": source["source_url"],
            "accent": source["accent"],
            "accent_source": blob_url(repository, pinned_revision, "voices/README.md"),
            "accent_confidence": "upstream_unverified",
            "attribution_status": status,
            "attribution_filename": attribution_name,
            "language_source": blob_url(repository, pinned_revision, "README.md"),
            "source_evidence": evidence_common,
            "synthetic": False,
        }
        if alias is not None:
            metadata["attribution_override_reason"] = alias[1]
        original_metadata[path] = metadata
        discovered.append(
            _row_for_file(
                repository=repository,
                revision=pinned_revision,
                source_path=path,
                item=item,
                variant="original",
                base_id=None,
                metadata=metadata,
                previous_by_id=previous_by_id,
                integrity_by_path=integrity_by_path,
            )
        )

    for path in emotion_paths:
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "voices-emotion":
            raise CatalogError(f"Voice-Zero emotion path must be speaker/emotion FLAC: {path}")
        _, speaker_id, filename = parts
        emotion = filename.removesuffix(".flac")
        if _EMOTION_RE.fullmatch(emotion) is None:
            raise CatalogError(f"Voice-Zero emotion tag is not normalized: {emotion!r}")
        base_path = f"voices/{speaker_id}.flac"
        if base_path in exclusions:
            quarantined.append(
                {
                    "source_path": path,
                    "reason": f"base original {base_path} is excluded: {exclusions[base_path]}",
                }
            )
            continue
        if base_path not in original_metadata:
            raise CatalogError(f"Voice-Zero emotion {path} has no unambiguous original base")
        base_id = base_path.removesuffix(".flac")
        metadata = dict(original_metadata[base_path])
        metadata.update(
            {
                "emotion": emotion,
                "synthetic": True,
                "synthesis_tool": "Chatterbox",
                "post_processing_tool": "Resemble Enhance",
                "source_evidence": [
                    *evidence_common,
                    blob_url(repository, pinned_revision, "voices-emotion/README.md"),
                ],
            }
        )
        discovered.append(
            _row_for_file(
                repository=repository,
                revision=pinned_revision,
                source_path=path,
                item=tree[path],
                variant="emotion",
                base_id=base_id,
                metadata=metadata,
                previous_by_id=previous_by_id,
                integrity_by_path=integrity_by_path,
            )
        )

    merged = merge_immutable_rows(previous_rows, discovered)
    result: dict[str, Any] = {
        "schema": 1,
        "kind": "voicefolio-catalog",
        "namespace": NAMESPACE,
        "source_repository": repository,
        "source_revision": pinned_revision,
        "voices": merged,
        "quarantined": sorted(quarantined, key=lambda item: item["source_path"]),
    }
    verify_voice_zero_catalog(result)
    return result


def verify_voice_zero_catalog(catalog: Mapping[str, Any]) -> None:
    """Validate Voice-Zero provenance, licensing, paths, pins, variants, and links."""
    if catalog.get("schema") != 1 or catalog.get("kind") != "voicefolio-catalog":
        raise CatalogError("Voice-Zero catalog schema/kind is invalid")
    if catalog.get("namespace") != NAMESPACE:
        raise CatalogError(f"Voice-Zero namespace must be {NAMESPACE!r}")
    repository = catalog.get("source_repository")
    revision = catalog.get("source_revision")
    if repository != DEFAULT_REPOSITORY:
        raise CatalogError(f"Voice-Zero repository must be {DEFAULT_REPOSITORY!r}")
    if not isinstance(revision, str) or _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Voice-Zero catalog revision must be a full 40-character commit SHA")
    rows = catalog.get("voices")
    if not isinstance(rows, list):
        raise CatalogError("Voice-Zero voices must be an array")

    ids: list[str] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"voices[{index}]")
        voice_id = row.get("id")
        if not isinstance(voice_id, str) or _ID_RE.fullmatch(voice_id) is None:
            raise CatalogError(f"Voice-Zero row {index} has an unsafe stable id")
        if voice_id in by_id:
            raise CatalogError(f"Voice-Zero catalog repeats stable id {voice_id!r}")
        ids.append(voice_id)
        by_id[voice_id] = row
        source_path = _safe_path(row.get("source_path"), f"{voice_id} source path")
        if row.get("dataset") != NAMESPACE or row.get("language") != "en":
            raise CatalogError(f"Voice-Zero {voice_id}: dataset/language is invalid")
        if row.get("source_repository") != repository:
            raise CatalogError(f"Voice-Zero {voice_id}: source repository differs from catalog")
        row_revision = row.get("source_revision")
        if not isinstance(row_revision, str) or _SHA_RE.fullmatch(row_revision) is None:
            raise CatalogError(
                f"Voice-Zero {voice_id}: source revision is not a full commit SHA"
            )
        if row.get("format") != "flac" or not source_path.endswith(".flac"):
            raise CatalogError(f"Voice-Zero {voice_id}: source must be a FLAC file")
        if row.get("url") != raw_url(repository, row_revision, source_path):
            raise CatalogError(f"Voice-Zero {voice_id}: source URL is not revision-pinned")
        size = row.get("size")
        digest = row.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise CatalogError(f"Voice-Zero {voice_id}: source size must be positive")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise CatalogError(f"Voice-Zero {voice_id}: source SHA-256 is invalid")
        if row.get("license") != _LICENSE:
            raise CatalogError(f"Voice-Zero {voice_id}: license must be {_LICENSE}")
        if row.get("license_evidence") != blob_url(repository, row_revision, "LICENSE.md"):
            raise CatalogError(
                f"Voice-Zero {voice_id}: license evidence is not revision-pinned"
            )
        metadata = _mapping(row.get("metadata"), f"{voice_id} metadata")
        blob_id = metadata.get("source_blob_id")
        if not isinstance(blob_id, str) or _SHA_RE.fullmatch(blob_id) is None:
            raise CatalogError(f"Voice-Zero {voice_id}: source Git blob identity is invalid")
        if not isinstance(metadata.get("speaker_id"), str) or not metadata["speaker_id"]:
            raise CatalogError(f"Voice-Zero {voice_id}: speaker id is required")
        if (
            not isinstance(metadata.get("speaker_name"), str)
            or not metadata["speaker_name"].strip()
        ):
            raise CatalogError(f"Voice-Zero {voice_id}: reviewed speaker name is required")
        if metadata.get("language_source") != blob_url(repository, row_revision, "README.md"):
            raise CatalogError(
                f"Voice-Zero {voice_id}: language evidence is not revision-pinned"
            )
        if metadata.get("attribution_status") not in {
            "reviewed_exact_filename",
            "reviewed_filename_override",
        }:
            raise CatalogError(f"Voice-Zero {voice_id}: attribution mapping is not reviewed")
        if (
            not isinstance(metadata.get("source_title"), str)
            or not metadata["source_title"].strip()
        ):
            raise CatalogError(f"Voice-Zero {voice_id}: source title is required")
        _https_url(metadata.get("source_url"), f"{voice_id} source attribution URL")
        _https_url(metadata.get("speaker_url"), f"{voice_id} speaker URL", optional=True)
        accent = metadata.get("accent")
        if not isinstance(accent, str) or not accent.strip():
            raise CatalogError(f"Voice-Zero {voice_id}: source accent label is required")
        if metadata.get("accent_confidence") != "upstream_unverified":
            raise CatalogError(
                f"Voice-Zero {voice_id}: accent confidence must remain conservative"
            )
        if metadata.get("accent_source") != blob_url(
            repository, row_revision, "voices/README.md"
        ):
            raise CatalogError(f"Voice-Zero {voice_id}: accent evidence is not revision-pinned")
        expected_evidence = [
            blob_url(repository, row_revision, "README.md"),
            blob_url(repository, row_revision, "LICENSE.md"),
            blob_url(repository, row_revision, "voices/README.md"),
        ]
        if row.get("variant") == "emotion":
            expected_evidence.append(
                blob_url(repository, row_revision, "voices-emotion/README.md")
            )
        source_evidence = metadata.get("source_evidence")
        if source_evidence != expected_evidence:
            raise CatalogError(
                f"Voice-Zero {voice_id}: source evidence URLs are incomplete or unpinned"
            )
        try:
            json.dumps(metadata, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise CatalogError(f"Voice-Zero {voice_id}: metadata is not JSON-safe") from exc

        variant = row.get("variant")
        base_id = row.get("base_id")
        if variant == "original":
            expected_id = source_path.removesuffix(".flac")
            if (
                not source_path.startswith("voices/")
                or source_path.count("/") != 1
                or voice_id != expected_id
                or base_id is not None
                or metadata.get("synthetic") is not False
            ):
                raise CatalogError(
                    f"Voice-Zero {voice_id}: original path/variant/base is invalid"
                )
            if metadata.get("speaker_id") != Path(source_path).name.removesuffix(".flac"):
                raise CatalogError(
                    f"Voice-Zero {voice_id}: speaker id does not match its source path"
                )
            attribution_filename = metadata.get("attribution_filename")
            status = metadata.get("attribution_status")
            if status == "reviewed_exact_filename":
                if attribution_filename != Path(source_path).name:
                    raise CatalogError(
                        f"Voice-Zero {voice_id}: filename attribution is not exact"
                    )
            elif status == "reviewed_filename_override":
                reason = metadata.get("attribution_override_reason")
                if (
                    attribution_filename == Path(source_path).name
                    or not isinstance(reason, str)
                    or not reason.strip()
                ):
                    raise CatalogError(
                        f"Voice-Zero {voice_id}: filename override lacks a reason"
                    )
        elif variant == "emotion":
            parts = source_path.split("/")
            emotion = parts[-1].removesuffix(".flac") if len(parts) == 3 else ""
            expected_id = source_path.removesuffix(".flac")
            if (
                not source_path.startswith("voices-emotion/")
                or len(parts) != 3
                or voice_id != expected_id
                or metadata.get("speaker_id") != parts[1]
                or not isinstance(base_id, str)
                or base_id != f"voices/{parts[1]}"
                or metadata.get("emotion") != emotion
                or _EMOTION_RE.fullmatch(emotion) is None
                or metadata.get("synthetic") is not True
                or metadata.get("synthesis_tool") != "Chatterbox"
                or metadata.get("post_processing_tool") != "Resemble Enhance"
            ):
                raise CatalogError(
                    f"Voice-Zero {voice_id}: emotion path/metadata/base is invalid"
                )
        else:
            raise CatalogError(f"Voice-Zero {voice_id}: unsupported variant {variant!r}")

    if ids != sorted(ids):
        raise CatalogError("Voice-Zero IDs must be sorted")
    quarantined = catalog.get("quarantined")
    if not isinstance(quarantined, list):
        raise CatalogError("Voice-Zero quarantined paths must be an array")
    quarantine_paths: list[str] = []
    for index, raw in enumerate(quarantined):
        record = _mapping(raw, f"quarantined[{index}]")
        path = _safe_path(record.get("source_path"), f"quarantined[{index}] source path")
        reason = record.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise CatalogError(f"Voice-Zero quarantined path {path} has no diagnostic")
        quarantine_paths.append(path)
    if quarantine_paths != sorted(set(quarantine_paths)):
        raise CatalogError("Voice-Zero quarantined paths must be sorted and unique")
    included_paths = {str(row.get("source_path")) for row in rows if isinstance(row, Mapping)}
    if included_paths.intersection(quarantine_paths):
        raise CatalogError("Voice-Zero catalog includes paths that are marked quarantined")

    for voice_id, row in by_id.items():
        if row.get("variant") == "emotion":
            base_id = row.get("base_id")
            base = by_id.get(str(base_id))
            if base is None or base.get("variant") != "original":
                raise CatalogError(
                    f"Voice-Zero {voice_id}: emotion base is missing or not original"
                )
            base_metadata = base.get("metadata")
            emotion_metadata = row.get("metadata")
            if (
                not isinstance(base_metadata, Mapping)
                or not isinstance(emotion_metadata, Mapping)
                or base_metadata.get("speaker_id") != emotion_metadata.get("speaker_id")
                or base_metadata.get("speaker_name") != emotion_metadata.get("speaker_name")
            ):
                raise CatalogError(
                    f"Voice-Zero {voice_id}: emotion speaker differs from its base"
                )
