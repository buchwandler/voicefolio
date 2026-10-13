from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Any
from collections.abc import Iterable, Mapping

from .models import CatalogError, VoiceEntry, VoiceNotFoundError, VoiceRef

CATALOG_SCHEMA = 1
CATALOG_KIND = "voicefolio-catalog"


class Catalog:
    """Merged immutable view over one or more Voicefolio catalog files."""

    def __init__(self, entries: Iterable[VoiceEntry] = ()) -> None:
        by_ref: dict[str, VoiceEntry] = {}
        for entry in entries:
            key = str(entry.ref)
            previous = by_ref.get(key)
            if previous is not None and previous.sha256 != entry.sha256:
                raise CatalogError(
                    f"stable voice id {key!r} maps to multiple SHA-256 values: "
                    f"{previous.sha256} != {entry.sha256}"
                )
            by_ref[key] = entry
        self._entries = by_ref

    def __len__(self) -> int:
        return len(self._entries)

    def refs(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, ref: str | VoiceRef) -> VoiceEntry:
        key = str(ref) if isinstance(ref, VoiceRef) else str(VoiceRef.parse(ref))
        try:
            return self._entries[key]
        except KeyError as exc:
            raise VoiceNotFoundError(f"voice {key!r} is not in the active catalog") from exc

    def list(
        self,
        *,
        namespace: str | None = None,
        dataset: str | None = None,
        variant: str | None = None,
        license: str | None = None,
        query: str | None = None,
    ) -> tuple[VoiceEntry, ...]:
        query_l = query.lower() if query else None
        rows = []
        for entry in self._entries.values():
            if namespace and entry.ref.namespace != namespace:
                continue
            if dataset and entry.dataset != dataset:
                continue
            if variant and entry.variant != variant:
                continue
            if license and entry.license != license:
                continue
            if (
                query_l
                and query_l not in str(entry.ref).lower()
                and query_l not in entry.dataset.lower()
            ):
                continue
            rows.append(entry)
        return tuple(sorted(rows, key=lambda item: str(item.ref)))

    @classmethod
    def from_paths(cls, paths: Iterable[str | Path]) -> Catalog:
        entries: list[VoiceEntry] = []
        for path in paths:
            entries.extend(_read_catalog(Path(path)))
        return cls(entries)

    @classmethod
    def builtin(cls) -> Catalog:
        package_dir = files("voicefolio").joinpath("resources", "catalogs")
        entries: list[VoiceEntry] = []
        for resource in package_dir.iterdir():
            if resource.name.endswith(".json"):
                with resource.open("r", encoding="utf-8") as handle:
                    entries.extend(_parse_catalog(json.load(handle), source=resource.name))
        return cls(entries)

    def merged(self, other: Catalog) -> Catalog:
        return Catalog((*self._entries.values(), *other._entries.values()))


def _read_catalog(path: Path) -> list[VoiceEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read catalog {path}: {exc}") from exc
    return _parse_catalog(raw, source=str(path))


def _required_mapping(value: Any, field: str, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogError(f"{source}: {field} must be an object")
    return value


def _parse_catalog(raw: Any, *, source: str) -> list[VoiceEntry]:
    data = _required_mapping(raw, "catalog", source)
    if data.get("schema") != CATALOG_SCHEMA:
        raise CatalogError(f"{source}: unsupported schema {data.get('schema')!r}")
    if data.get("kind") != CATALOG_KIND:
        raise CatalogError(f"{source}: kind must be {CATALOG_KIND!r}")
    namespace = data.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise CatalogError(f"{source}: namespace must be a non-empty string")
    raw_voices = data.get("voices")
    if not isinstance(raw_voices, list):
        raise CatalogError(f"{source}: voices must be an array")
    result: list[VoiceEntry] = []
    for index, value in enumerate(raw_voices):
        row = _required_mapping(value, f"voices[{index}]", source)
        try:
            result.append(
                VoiceEntry(
                    ref=VoiceRef(namespace, str(row["id"])),
                    dataset=str(row["dataset"]),
                    variant=str(row["variant"]),
                    base_id=row.get("base_id"),
                    format=str(row["format"]),
                    url=str(row["url"]),
                    size=int(row["size"]),
                    sha256=str(row["sha256"]),
                    source_repository=str(row["source_repository"]),
                    source_revision=str(row["source_revision"]),
                    source_path=str(row["source_path"]),
                    license=str(row["license"]),
                    license_note=row.get("license_note"),
                    license_evidence=row.get("license_evidence"),
                    metadata=_required_mapping(row.get("metadata", {}), "metadata", source),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogError(f"{source}: invalid voices[{index}]: {exc}") from exc
    return result


def load_catalog(extra_paths: Iterable[str | Path] = ()) -> Catalog:
    """Load packaged catalogs plus explicit paths and VOICEFOLIO_CATALOG_PATH."""
    catalog = Catalog.builtin()
    paths = [Path(path) for path in extra_paths]
    env = os.environ.get("VOICEFOLIO_CATALOG_PATH")
    if env:
        paths.extend(Path(value) for value in env.split(os.pathsep) if value)
    if paths:
        catalog = catalog.merged(Catalog.from_paths(paths))
    return catalog
