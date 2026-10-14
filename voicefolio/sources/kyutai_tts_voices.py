from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from ..catalog import CATALOG_KIND, CATALOG_SCHEMA
from ..models import CatalogError, VoiceRef
from .huggingface import (
    blob_url,
    file_integrity,
    repository_tree,
    resolve_revision,
    resolve_url,
)

DEFAULT_REPOSITORY = "kyutai/tts-voices"
DEFAULT_REVISION = "main"
NAMESPACE = "kyutai-tts-voices"
_LICENSES = frozenset({"CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0", "NOASSERTION"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POLICY_RESOURCE = "kyutai-tts-voices-licenses.json"
_LANGUAGE_POLICY_RESOURCE = "kyutai-tts-voices-languages.json"
_SUPPORTED_LANGUAGES = frozenset({"en", "fr", "und"})


def load_license_policy() -> dict[str, Any]:
    """Load the single packaged source of Kyutai license decisions."""
    resource = (
        files("voicefolio").joinpath("resources").joinpath("sources").joinpath(_POLICY_RESOURCE)
    )
    try:
        with resource.open("r", encoding="utf-8") as handle:
            policy = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read Kyutai license policy: {exc}") from exc
    if not isinstance(policy, dict):
        raise CatalogError("Kyutai license policy root must be an object")
    return policy


def load_language_policy() -> dict[str, Any]:
    """Load the packaged fail-closed Kyutai language decisions."""
    resource = (
        files("voicefolio")
        .joinpath("resources")
        .joinpath("sources")
        .joinpath(_LANGUAGE_POLICY_RESOURCE)
    )
    try:
        with resource.open("r", encoding="utf-8") as handle:
            policy = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read Kyutai language policy: {exc}") from exc
    if not isinstance(policy, dict):
        raise CatalogError("Kyutai language policy root must be an object")
    return policy


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogError(f"{label} must be an object")
    return value


def _safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise CatalogError(f"{label}: unsafe relative path")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise CatalogError(f"{label}: whitespace/control characters are forbidden")
    if re.match(r"^[A-Za-z]:", value):
        raise CatalogError(f"{label}: absolute paths are forbidden")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise CatalogError(f"{label}: unsafe path component")
    return value


def _license_decision(value: Any, label: str) -> tuple[str, str | None]:
    row = _mapping(value, label)
    license_name = row.get("license")
    note = row.get("license_note")
    if not isinstance(license_name, str) or license_name not in _LICENSES:
        raise CatalogError(f"{label}: unsupported license {license_name!r}")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise CatalogError(f"{label}: license_note must be a non-empty string or null")
    if license_name == "NOASSERTION" and not note:
        raise CatalogError(f"{label}: NOASSERTION requires license_note")
    return license_name, note


def resolve_license(
    source_path: str, policy: Mapping[str, Any] | None = None
) -> tuple[str, str | None]:
    """Return the unique policy decision for a WAV path; exact overrides win over prefixes."""
    path = _safe_relative_path(source_path, "source path")
    if not path.endswith(".wav"):
        raise CatalogError(f"{path}: license policy applies to WAV files only")
    active_policy = policy if policy is not None else load_license_policy()
    overrides = _mapping(active_policy.get("overrides", {}), "license policy overrides")
    if path in overrides:
        return _license_decision(overrides[path], f"license override for {path}")

    rules = active_policy.get("rules")
    if not isinstance(rules, list):
        raise CatalogError("license policy rules must be an array")
    matches: list[Mapping[str, Any]] = []
    for index, raw_rule in enumerate(rules):
        rule = _mapping(raw_rule, f"license policy rules[{index}]")
        prefix = rule.get("prefix")
        if not isinstance(prefix, str) or not prefix:
            raise CatalogError(f"license policy rules[{index}]: prefix must be non-empty")
        if path.startswith(prefix):
            matches.append(rule)
    if len(matches) != 1:
        reason = "no" if not matches else "multiple"
        raise CatalogError(f"{path}: {reason} unique license rule covers this source path")
    return _license_decision(matches[0], f"license rule for {path}")


def _language_decision(value: Any, label: str) -> str:
    if not isinstance(value, str) or value not in _SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(_SUPPORTED_LANGUAGES))
        raise CatalogError(f"{label}: unsupported language {value!r}; expected {supported}")
    return value


def resolve_language(source_path: str, policy: Mapping[str, Any] | None = None) -> str:
    """Return the unique policy language for a source path; exact overrides win."""
    path = _safe_relative_path(source_path, "source path")
    if not path.endswith(".wav"):
        raise CatalogError(f"{path}: language policy applies to WAV files only")
    active_policy = policy if policy is not None else load_language_policy()
    if active_policy.get("source_repository") != DEFAULT_REPOSITORY:
        raise CatalogError("Kyutai language policy source_repository is invalid")
    overrides = _mapping(active_policy.get("overrides", {}), "language policy overrides")
    normalized_overrides: dict[str, str] = {}
    for override_path, value in overrides.items():
        safe_path = _safe_relative_path(override_path, "language policy override path")
        if not safe_path.endswith(".wav"):
            raise CatalogError(f"{safe_path}: language override must target a WAV file")
        normalized_overrides[safe_path] = _language_decision(
            value, f"language override for {safe_path}"
        )
    if path in normalized_overrides:
        return normalized_overrides[path]

    rules = active_policy.get("rules")
    if not isinstance(rules, list):
        raise CatalogError("language policy rules must be an array")
    matches: list[str] = []
    for index, raw_rule in enumerate(rules):
        rule = _mapping(raw_rule, f"language policy rules[{index}]")
        prefix = rule.get("prefix")
        if not isinstance(prefix, str) or not prefix.endswith("/"):
            raise CatalogError(
                f"language policy rules[{index}]: prefix must be a non-empty relative path prefix"
            )
        _safe_relative_path(prefix[:-1], f"language policy rules[{index}] prefix")
        language = _language_decision(rule.get("language"), f"language policy rules[{index}]")
        if path.startswith(prefix):
            matches.append(language)
    if len(matches) != 1:
        reason = "no" if not matches else "multiple"
        raise CatalogError(f"{path}: {reason} unique language rule covers this source path")
    return matches[0]


def _read_catalog(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read previous catalog {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogError(f"previous catalog {path} must contain an object")
    return raw


def _revision(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise CatalogError(f"{label} must be a lowercase 40-character commit SHA")
    return value


def discover_snapshot(
    repository: str = DEFAULT_REPOSITORY,
    revision: str = DEFAULT_REVISION,
    *,
    license_policy: Mapping[str, Any] | None = None,
    language_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover and pin every WAV in one exact Kyutai repository snapshot."""
    policy = license_policy if license_policy is not None else load_license_policy()
    language_rules = language_policy if language_policy is not None else load_language_policy()
    if language_rules.get("source_repository") != repository:
        raise CatalogError(
            "language policy source repository differs from requested repository"
        )
    source_repository = policy.get("source_repository")
    source_readme = policy.get("source_readme")
    if source_repository != repository:
        raise CatalogError(
            f"license policy is for {source_repository!r}, not requested repository {repository!r}"
        )
    if not isinstance(source_readme, str) or not source_readme:
        raise CatalogError("license policy source_readme must be a non-empty path")
    _safe_relative_path(source_readme, "license policy source_readme")

    actual_revision = _revision(resolve_revision(repository, revision), "resolved revision")
    rows: list[dict[str, Any]] = []
    for metadata in repository_tree(repository, actual_revision):
        path_value = metadata.get("path")
        if not isinstance(path_value, str) or not path_value.endswith(".wav"):
            continue
        source_path = _safe_relative_path(path_value, "source path")
        voice_id = source_path.removesuffix(".wav")
        VoiceRef(NAMESPACE, voice_id)
        dataset = voice_id.split("/", 1)[0]
        variant = "enhanced" if voice_id.endswith("_enhanced") else "original"
        base_id = voice_id.removesuffix("_enhanced") if variant == "enhanced" else None
        size, sha256 = file_integrity(repository, actual_revision, source_path, metadata)
        license_name, license_note = resolve_license(source_path, policy)
        language = resolve_language(source_path, language_rules)
        rows.append(
            {
                "id": voice_id,
                "dataset": dataset,
                "language": language,
                "variant": variant,
                "base_id": base_id,
                "format": "wav",
                "url": resolve_url(repository, actual_revision, source_path),
                "size": size,
                "sha256": sha256,
                "source_repository": repository,
                "source_revision": actual_revision,
                "source_path": source_path,
                "license": license_name,
                "license_note": license_note,
                "license_evidence": blob_url(repository, actual_revision, source_readme),
                "metadata": {},
            }
        )
    rows.sort(key=lambda item: item["id"])
    if not rows:
        raise CatalogError(f"No WAV files found in {repository}@{actual_revision}")
    catalog = {
        "schema": CATALOG_SCHEMA,
        "kind": CATALOG_KIND,
        "namespace": NAMESPACE,
        "source": {
            "provider": "huggingface",
            "repository": repository,
            "requested_revision": revision,
            "revision": actual_revision,
            "prompt_count": len(rows),
            "license": "mixed",
        },
        "voices": rows,
    }
    verify_kyutai_catalog(catalog, license_policy=policy, language_policy=language_rules)
    return catalog


def _catalog_rows(catalog: Mapping[str, Any], label: str) -> list[Mapping[str, Any]]:
    voices = catalog.get("voices")
    if not isinstance(voices, list):
        raise CatalogError(f"{label}: voices must be an array")
    result: list[Mapping[str, Any]] = []
    for index, row in enumerate(voices):
        result.append(_mapping(row, f"{label}: voices[{index}]"))
    return result


def verify_kyutai_catalog(
    catalog: Mapping[str, Any],
    *,
    license_policy: Mapping[str, Any] | None = None,
    language_policy: Mapping[str, Any] | None = None,
) -> None:
    """Raise CatalogError unless a schema-1 Kyutai catalog satisfies maintainer invariants."""
    policy = license_policy if license_policy is not None else load_license_policy()
    language_rules = language_policy if language_policy is not None else load_language_policy()
    data = _mapping(catalog, "catalog")
    if data.get("schema") != CATALOG_SCHEMA or isinstance(data.get("schema"), bool):
        raise CatalogError(f"catalog schema must be {CATALOG_SCHEMA}")
    if data.get("kind") != CATALOG_KIND:
        raise CatalogError(f"catalog kind must be {CATALOG_KIND!r}")
    if data.get("namespace") != NAMESPACE:
        raise CatalogError(f"catalog namespace must be {NAMESPACE!r}")

    source = _mapping(data.get("source"), "catalog source")
    repository = source.get("repository")
    if not isinstance(repository, str) or not repository:
        raise CatalogError("catalog source repository must be non-empty")
    top_revision = _revision(source.get("revision"), "catalog discovery revision")
    requested_revision = source.get("requested_revision")
    if not isinstance(requested_revision, str) or not requested_revision:
        raise CatalogError("catalog requested_revision must be non-empty")
    policy_repository = policy.get("source_repository")
    if language_rules.get("source_repository") != repository:
        raise CatalogError("catalog source repository does not match the language policy")
    source_readme = policy.get("source_readme")
    if repository != policy_repository:
        raise CatalogError("catalog source repository does not match the license policy")
    if not isinstance(source_readme, str) or not source_readme:
        raise CatalogError("license policy source_readme must be a non-empty path")

    rows = _catalog_rows(data, "catalog")
    if not rows:
        raise CatalogError("Kyutai catalog must contain at least one voice")
    ids: list[str] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    digest_by_ref: dict[str, str] = {}
    for index, row in enumerate(rows):
        label = f"voices[{index}]"
        voice_id = _safe_relative_path(row.get("id"), f"{label} id")
        VoiceRef(NAMESPACE, voice_id)
        if voice_id.endswith(".wav"):
            raise CatalogError(f"{label} id must not include the .wav extension")
        source_path = _safe_relative_path(row.get("source_path"), f"{label} source_path")
        if not source_path.endswith(".wav") or source_path != f"{voice_id}.wav":
            raise CatalogError(f"{label} source_path must be the .wav path for its id")
        dataset = voice_id.split("/", 1)[0]
        if row.get("dataset") != dataset:
            raise CatalogError(f"{label} dataset must be the first id path component")
        if row.get("format") != "wav":
            raise CatalogError(f"{label} format must be 'wav'")
        size = row.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise CatalogError(f"{label} size must be a positive integer")
        sha256 = row.get("sha256")
        if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
            raise CatalogError(f"{label} sha256 must be 64 lowercase hexadecimal characters")
        row_repository = row.get("source_repository")
        if not isinstance(row_repository, str) or not row_repository:
            raise CatalogError(f"{label} source_repository must be non-empty")
        if row_repository != repository:
            raise CatalogError(f"{label} source_repository differs from catalog source")
        row_revision = _revision(row.get("source_revision"), f"{label} source_revision")
        expected_url = resolve_url(row_repository, row_revision, source_path)
        if row.get("url") != expected_url:
            raise CatalogError(f"{label} URL must be pinned to its source revision and path")
        expected_language = resolve_language(source_path, language_rules)
        actual_language = _language_decision(row.get("language"), label)
        if actual_language != expected_language:
            raise CatalogError(f"{label} language differs from the authoritative policy")
        license_name, license_note = resolve_license(source_path, policy)
        actual_license, actual_note = _license_decision(row, label)
        if actual_license != license_name or actual_note != license_note:
            raise CatalogError(
                f"{label} license decision differs from the authoritative policy"
            )
        evidence = blob_url(row_repository, row_revision, source_readme)
        if row.get("license_evidence") != evidence:
            raise CatalogError(f"{label} license_evidence must point at its pinned README")
        if not isinstance(row.get("metadata", {}), Mapping):
            raise CatalogError(f"{label} metadata must be an object")

        expected_variant = "enhanced" if voice_id.endswith("_enhanced") else "original"
        expected_base = (
            voice_id.removesuffix("_enhanced") if expected_variant == "enhanced" else None
        )
        if row.get("variant") != expected_variant or row.get("base_id") != expected_base:
            raise CatalogError(f"{label} variant/base_id does not match its stable id")
        if voice_id in by_id:
            previous_digest = digest_by_ref[voice_id]
            if previous_digest != sha256:
                raise CatalogError(
                    f"duplicate ref {NAMESPACE}:{voice_id} maps to multiple SHA-256 values"
                )
            raise CatalogError(f"duplicate ref {NAMESPACE}:{voice_id}")
        ids.append(voice_id)
        by_id[voice_id] = row
        digest_by_ref[voice_id] = sha256

    if ids != sorted(ids):
        raise CatalogError("Kyutai catalog voices must be sorted by unique id")
    for voice_id, row in by_id.items():
        if row.get("variant") == "enhanced":
            base_id = row.get("base_id")
            base = by_id.get(base_id) if isinstance(base_id, str) else None
            if base is None or base.get("variant") != "original":
                raise CatalogError(f"enhanced voice {voice_id} is missing its original base id")
    # Discovery metadata describes this scan; historical rows may be pinned elsewhere.
    if not _SHA_RE.fullmatch(top_revision):
        raise CatalogError("catalog discovery revision must be a 40-character commit SHA")


def build_catalog(
    previous_catalog: Mapping[str, Any] | str | Path | None = None,
    *,
    repository: str = DEFAULT_REPOSITORY,
    revision: str = DEFAULT_REVISION,
    license_policy: Mapping[str, Any] | None = None,
    language_policy: Mapping[str, Any] | None = None,
    discovered_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a latest-discovery catalog while preserving published ref identities."""
    policy = license_policy if license_policy is not None else load_license_policy()
    language_rules = language_policy if language_policy is not None else load_language_policy()
    discovered = (
        copy.deepcopy(dict(discovered_snapshot))
        if discovered_snapshot is not None
        else discover_snapshot(
            repository,
            revision,
            license_policy=policy,
            language_policy=language_rules,
        )
    )
    verify_kyutai_catalog(discovered, license_policy=policy, language_policy=language_rules)
    if previous_catalog is None:
        return discovered

    previous = _read_catalog(previous_catalog)
    verify_kyutai_catalog(previous, license_policy=policy, language_policy=language_rules)
    previous_rows = _catalog_rows(previous, "previous catalog")
    discovered_rows = _catalog_rows(discovered, "discovered snapshot")
    previous_by_id = {str(row["id"]): row for row in previous_rows}
    discovered_by_id = {str(row["id"]): row for row in discovered_rows}

    merged_by_id: dict[str, Mapping[str, Any]] = dict(previous_by_id)
    for voice_id, current_row in discovered_by_id.items():
        published = previous_by_id.get(voice_id)
        if published is None:
            merged_by_id[voice_id] = current_row
            continue
        old_sha = published.get("sha256")
        new_sha = current_row.get("sha256")
        if old_sha != new_sha:
            raise CatalogError(
                "Stable voice ref collision: "
                f"{NAMESPACE}:{voice_id} was previously {old_sha} and upstream now reports "
                f"{new_sha}. Published refs are immutable. Mint a new ID or record an explicit "
                "maintainer decision."
            )
        # Preserve the published row exactly, even if discovery sees the same audio at a new SHA.
        merged_by_id[voice_id] = published

    result = copy.deepcopy(discovered)
    result["voices"] = [
        copy.deepcopy(dict(merged_by_id[voice_id])) for voice_id in sorted(merged_by_id)
    ]
    verify_kyutai_catalog(result, license_policy=policy, language_policy=language_rules)
    return result
