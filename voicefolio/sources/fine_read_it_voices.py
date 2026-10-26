"""Maintainer builder and verifier for the Fine Read It reference-voice dataset."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..errors import CatalogError
from .base import merge_immutable_rows
from .huggingface import (
    dataset_blob_url,
    dataset_resolve_url,
    file_integrity,
    read_file,
    repository_tree,
    resolve_revision,
)

NAMESPACE = "fine-read-it-voices"
DEFAULT_REPOSITORY = "zloezlo/fine-read-it-voices"
_LICENSE = "CC-BY-4.0"
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogError(f"Fine Read It {label} must be an object")
    return value


def _read_json(repository: str, revision: str, path: str) -> Any:
    payload = read_file(repository, revision, path, max_bytes=4 * 1024 * 1024)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Fine Read It {path} is not valid UTF-8 JSON") from exc


def _text_from_bytes(payload: bytes, path: str) -> str:
    try:
        text = payload.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise CatalogError(f"Fine Read It transcript {path} is not valid UTF-8") from exc
    if not text:
        raise CatalogError(f"Fine Read It transcript {path} is empty")
    return text


def _transcript(repository: str, revision: str, voice_id: str) -> str:
    path = f"{voice_id}.txt"
    return _text_from_bytes(
        read_file(repository, revision, path, max_bytes=64 * 1024),
        path,
    )


def _previous_rows(
    previous_path: str | Path | None,
    *,
    bootstrap: bool,
    repository: str,
) -> list[Mapping[str, Any]]:
    if previous_path is None:
        if not bootstrap:
            raise CatalogError("first Fine Read It build requires explicit bootstrap mode")
        return []
    path = Path(previous_path)
    if not path.exists():
        raise CatalogError(f"previous Fine Read It catalog does not exist: {path}")
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read previous Fine Read It catalog {path}: {exc}") from exc
    _mapping(previous, "previous catalog")
    verify_fine_read_it_catalog(previous)
    if previous.get("source_repository") != repository:
        raise CatalogError("previous Fine Read It catalog uses a different source repository")
    voices = previous.get("voices")
    if not isinstance(voices, list) or any(not isinstance(row, Mapping) for row in voices):
        raise CatalogError("previous Fine Read It catalog voices must be an array of objects")
    return voices


def build_catalog(
    previous_path: str | Path | None = None,
    *,
    repository: str = DEFAULT_REPOSITORY,
    revision: str = "main",
    bootstrap: bool = False,
) -> dict[str, Any]:
    """Build a deterministic Fine Read It catalog from a pinned Hugging Face snapshot."""
    if repository != DEFAULT_REPOSITORY:
        raise CatalogError(f"Fine Read It repository must be {DEFAULT_REPOSITORY!r}")
    previous_rows = _previous_rows(
        previous_path,
        bootstrap=bootstrap,
        repository=repository,
    )
    pinned_revision = resolve_revision(repository, revision, repo_kind="dataset")
    if _SHA_RE.fullmatch(pinned_revision) is None:
        raise CatalogError("Fine Read It revision did not resolve to a 40-character commit")

    raw_pool = _read_json(repository, pinned_revision, "pool.json")
    if not isinstance(raw_pool, list) or not raw_pool:
        raise CatalogError("Fine Read It pool.json must contain a non-empty array")
    pool: dict[str, Mapping[str, Any]] = {}
    for index, raw_row in enumerate(raw_pool):
        row = _mapping(raw_row, f"pool.json row {index}")
        voice_id = row.get("id")
        if not isinstance(voice_id, str) or _ID_RE.fullmatch(voice_id) is None:
            raise CatalogError(f"Fine Read It pool row {index} has an unsafe id")
        if voice_id in pool:
            raise CatalogError(f"Fine Read It pool.json contains duplicate id {voice_id!r}")
        pool[voice_id] = row

    tree = repository_tree(repository, pinned_revision, repo_kind="dataset")
    by_path: dict[str, Mapping[str, Any]] = {}
    for item in tree:
        if not isinstance(item, Mapping):
            raise CatalogError("Fine Read It tree contains a malformed entry")
        path = item.get("path")
        if item.get("type") == "file" and isinstance(path, str):
            if path in by_path:
                raise CatalogError(f"Fine Read It tree contains duplicate path {path!r}")
            by_path[path] = item

    attribution_bytes = read_file(
        repository,
        pinned_revision,
        "ATTRIBUTION.txt",
        max_bytes=1024 * 1024,
    )
    attribution = _text_from_bytes(attribution_bytes, "ATTRIBUTION.txt")
    attribution_lines: dict[str, str] = {}
    for line in attribution.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.+)$", line)
        if match:
            voice_id = match.group(1)
            if voice_id in attribution_lines:
                raise CatalogError(f"Fine Read It attribution repeats id {voice_id!r}")
            attribution_lines[voice_id] = line.strip()

    ids = sorted(pool)
    missing_refs = [voice_id for voice_id in ids if f"{voice_id}.wav" not in by_path]
    if missing_refs:
        raise CatalogError(
            f"Fine Read It reference WAVs missing from pinned tree: {missing_refs[:5]}"
        )
    missing_attribution = [voice_id for voice_id in ids if voice_id not in attribution_lines]
    if missing_attribution:
        raise CatalogError(f"Fine Read It attribution missing IDs: {missing_attribution[:5]}")
    missing_transcripts = [voice_id for voice_id in ids if f"{voice_id}.txt" not in by_path]
    if missing_transcripts:
        raise CatalogError(
            f"Fine Read It transcripts missing from pinned tree: {missing_transcripts[:5]}"
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        transcripts = list(
            executor.map(
                lambda voice_id: _transcript(repository, pinned_revision, voice_id), ids
            )
        )

    voices: list[dict[str, Any]] = []
    for voice_id, transcript in zip(ids, transcripts, strict=True):
        raw_row = pool[voice_id]
        reader = raw_row.get("reader")
        source = raw_row.get("source")
        gender = raw_row.get("gender")
        pitch_band = raw_row.get("band")
        f0 = raw_row.get("f0")
        qa = raw_row.get("qa", {})
        license_text = raw_row.get("license")
        if not isinstance(reader, str) or not reader.strip():
            raise CatalogError(f"Fine Read It {voice_id}: reader metadata is required")
        if not isinstance(source, str) or not source.strip():
            raise CatalogError(f"Fine Read It {voice_id}: source metadata is required")
        source_match = re.match(
            r"^(?P<subset>.+?)\s+speaker\s+(?P<speaker_id>\d+)(?:\s|$)", source
        )
        if source_match is None:
            raise CatalogError(
                f"Fine Read It {voice_id}: source speaker provenance is malformed"
            )
        source_subset = source_match.group("subset").strip()
        source_speaker_id = source_match.group("speaker_id")
        if gender not in {"male", "female"}:
            raise CatalogError(f"Fine Read It {voice_id}: unsupported gender {gender!r}")
        if pitch_band not in {"low", "mid", "high"}:
            raise CatalogError(
                f"Fine Read It {voice_id}: unsupported pitch band {pitch_band!r}"
            )
        if (
            isinstance(f0, bool)
            or not isinstance(f0, (int, float))
            or not math.isfinite(f0)
            or f0 <= 0
        ):
            raise CatalogError(f"Fine Read It {voice_id}: f0 must be a finite positive number")
        if not isinstance(license_text, str) or "CC BY 4.0" not in license_text:
            raise CatalogError(
                f"Fine Read It {voice_id}: source license is not verified CC BY 4.0"
            )
        qa_mapping = _mapping(qa, f"{voice_id} QA metadata")
        try:
            json.dumps(qa_mapping, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise CatalogError(
                f"Fine Read It {voice_id}: QA metadata is not JSON-safe"
            ) from exc

        reference_path = f"{voice_id}.wav"
        size, digest = file_integrity(
            repository,
            pinned_revision,
            reference_path,
            by_path[reference_path],
            dataset=True,
        )
        preview_path = f"samples/{voice_id}.wav"
        metadata: dict[str, Any] = {
            "reader": reader,
            "speaker_id": source_speaker_id,
            "gender": gender,
            "f0_hz": float(f0),
            "pitch_band": pitch_band,
            "source_subset": source_subset,
            "source_reference": source,
            "transcript": transcript,
            "qa": dict(qa_mapping),
            "attribution": attribution_lines[voice_id],
            "source_license_text": license_text,
        }
        preview_metadata = by_path.get(preview_path)
        if preview_metadata is not None:
            demo_size, demo_sha = file_integrity(
                repository,
                pinned_revision,
                preview_path,
                preview_metadata,
                dataset=True,
            )
            metadata["preview_demo"] = {
                "kind": "synthesized_demo",
                "format": "wav",
                "url": dataset_resolve_url(repository, pinned_revision, preview_path),
                "path": preview_path,
                "size": demo_size,
                "sha256": demo_sha,
            }

        voices.append(
            {
                "id": voice_id,
                "dataset": NAMESPACE,
                "language": "en",
                "variant": "original",
                "base_id": None,
                "format": "wav",
                "url": dataset_resolve_url(repository, pinned_revision, reference_path),
                "size": size,
                "sha256": digest,
                "source_repository": repository,
                "source_revision": pinned_revision,
                "source_path": reference_path,
                "license": _LICENSE,
                "license_note": None,
                "license_evidence": dataset_blob_url(
                    repository, pinned_revision, "ATTRIBUTION.txt"
                ),
                "metadata": metadata,
            }
        )

    merged = merge_immutable_rows(previous_rows, voices)
    result = {
        "schema": 1,
        "kind": "voicefolio-catalog",
        "namespace": NAMESPACE,
        "source_repository": repository,
        "source_revision": pinned_revision,
        "voices": merged,
    }
    verify_fine_read_it_catalog(result)
    return result


def verify_fine_read_it_catalog(catalog: Mapping[str, Any]) -> None:
    """Check the packaged Fine Read It rows and independently pinned preview demos."""
    if catalog.get("schema") != 1 or catalog.get("kind") != "voicefolio-catalog":
        raise CatalogError("Fine Read It catalog schema/kind is invalid")
    if catalog.get("namespace") != NAMESPACE:
        raise CatalogError(f"Fine Read It catalog namespace must be {NAMESPACE!r}")
    repository = catalog.get("source_repository")
    revision = catalog.get("source_revision")
    if repository != DEFAULT_REPOSITORY:
        raise CatalogError(f"Fine Read It repository must be {DEFAULT_REPOSITORY!r}")
    if not isinstance(revision, str) or _SHA_RE.fullmatch(revision) is None:
        raise CatalogError("Fine Read It source revision must be a 40-character commit SHA")
    voices = catalog.get("voices")
    if not isinstance(voices, list):
        raise CatalogError("Fine Read It voices must be an array")
    ids: list[str] = []
    for index, raw in enumerate(voices):
        row = _mapping(raw, f"voices[{index}]")
        voice_id = row.get("id")
        if not isinstance(voice_id, str) or _ID_RE.fullmatch(voice_id) is None:
            raise CatalogError(f"Fine Read It row {index} has an unsafe id")
        ids.append(voice_id)
        if row.get("dataset") != NAMESPACE or row.get("language") != "en":
            raise CatalogError(f"Fine Read It {voice_id}: dataset/language is invalid")
        if row.get("variant") != "original" or row.get("base_id") is not None:
            raise CatalogError(f"Fine Read It {voice_id}: reference variant/base id is invalid")
        if row.get("format") != "wav" or row.get("source_path") != f"{voice_id}.wav":
            raise CatalogError(f"Fine Read It {voice_id}: reference must be {voice_id}.wav WAV")
        row_revision = row.get("source_revision")
        if row.get("source_repository") != repository:
            raise CatalogError(
                f"Fine Read It {voice_id}: source repository differs from catalog"
            )
        if not isinstance(row_revision, str) or _SHA_RE.fullmatch(row_revision) is None:
            raise CatalogError(
                f"Fine Read It {voice_id}: source revision is not a 40-character commit"
            )
        if row.get("url") != dataset_resolve_url(repository, row_revision, f"{voice_id}.wav"):
            raise CatalogError(f"Fine Read It {voice_id}: source URL is not revision-pinned")
        size = row.get("size")
        digest = row.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise CatalogError(f"Fine Read It {voice_id}: source size must be positive")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise CatalogError(f"Fine Read It {voice_id}: invalid source SHA-256")
        if row.get("license") != _LICENSE:
            raise CatalogError(f"Fine Read It {voice_id}: license must be {_LICENSE}")
        expected_evidence = dataset_blob_url(repository, row_revision, "ATTRIBUTION.txt")
        if row.get("license_evidence") != expected_evidence:
            raise CatalogError(f"Fine Read It {voice_id}: attribution evidence is not pinned")

        metadata = _mapping(row.get("metadata"), f"{voice_id} metadata")
        if not isinstance(metadata.get("speaker_id"), str) or not metadata["speaker_id"]:
            raise CatalogError(f"Fine Read It {voice_id}: speaker id is required")
        if not isinstance(metadata.get("reader"), str) or not metadata["reader"].strip():
            raise CatalogError(f"Fine Read It {voice_id}: reader is required")
        if metadata.get("gender") not in {"male", "female"}:
            raise CatalogError(f"Fine Read It {voice_id}: invalid gender")
        pitch_band = metadata.get("pitch_band")
        if pitch_band not in {"low", "mid", "high"}:
            raise CatalogError(f"Fine Read It {voice_id}: invalid pitch band")
        f0 = metadata.get("f0_hz")
        if (
            isinstance(f0, bool)
            or not isinstance(f0, (int, float))
            or not math.isfinite(f0)
            or f0 <= 0
        ):
            raise CatalogError(f"Fine Read It {voice_id}: f0 must be finite and positive")
        if (
            not isinstance(metadata.get("source_subset"), str)
            or not metadata["source_subset"].strip()
        ):
            raise CatalogError(f"Fine Read It {voice_id}: source subset is required")
        source_reference = metadata.get("source_reference")
        if not isinstance(source_reference, str) or not source_reference.strip():
            raise CatalogError(f"Fine Read It {voice_id}: source reference is required")
        source_match = re.match(
            r"^(.+?)\s+speaker\s+(\d+)(?:\s|$)",
            source_reference,
        )
        if (
            source_match is None
            or source_match.group(1).strip() != metadata["source_subset"]
            or source_match.group(2) != metadata["speaker_id"]
        ):
            raise CatalogError(
                f"Fine Read It {voice_id}: source/speaker metadata is inconsistent"
            )
        if (
            not isinstance(metadata.get("transcript"), str)
            or not metadata["transcript"].strip()
        ):
            raise CatalogError(f"Fine Read It {voice_id}: transcript is required")
        attribution = metadata.get("attribution")
        if (
            not isinstance(attribution, str)
            or voice_id not in attribution
            or "CC BY 4.0" not in attribution
        ):
            raise CatalogError(
                f"Fine Read It {voice_id}: row attribution is missing or incomplete"
            )
        if "CC BY 4.0" not in str(metadata.get("source_license_text", "")):
            raise CatalogError(f"Fine Read It {voice_id}: source license evidence is missing")
        qa = _mapping(metadata.get("qa"), f"{voice_id} QA metadata")
        try:
            json.dumps(qa, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise CatalogError(
                f"Fine Read It {voice_id}: QA metadata is not JSON-safe"
            ) from exc

        demo = metadata.get("preview_demo")
        if demo is not None:
            demo = _mapping(demo, f"{voice_id} synthesized demo")
            expected_path = f"samples/{voice_id}.wav"
            if demo.get("kind") != "synthesized_demo" or demo.get("format") != "wav":
                raise CatalogError(
                    f"Fine Read It {voice_id}: preview asset is not a synthesized WAV demo"
                )
            if demo.get("path") != expected_path or demo.get("path") == row.get("source_path"):
                raise CatalogError(
                    f"Fine Read It {voice_id}: demo path is not distinct from reference"
                )
            if demo.get("url") != dataset_resolve_url(repository, row_revision, expected_path):
                raise CatalogError(f"Fine Read It {voice_id}: demo URL is not revision-pinned")
            demo_size = demo.get("size")
            demo_sha = demo.get("sha256")
            if isinstance(demo_size, bool) or not isinstance(demo_size, int) or demo_size <= 0:
                raise CatalogError(f"Fine Read It {voice_id}: demo size must be positive")
            if not isinstance(demo_sha, str) or _SHA256_RE.fullmatch(demo_sha) is None:
                raise CatalogError(f"Fine Read It {voice_id}: invalid demo SHA-256")
            if demo_sha == digest:
                raise CatalogError(f"Fine Read It {voice_id}: demo hash matches reference hash")
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise CatalogError("Fine Read It IDs must be sorted and unique")
