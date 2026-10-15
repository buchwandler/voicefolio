from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .errors import (
    AccessError,
    AssetNotFoundError,
    CatalogError,
    DownloadError,
    IntegrityError,
    MaterializationError,
    MissingAudioDependencyError,
    OfflineError,
    PlaybackError,
    VoicefolioError,
    VoiceNotFoundError,
)

__all__ = [
    "AccessError",
    "AssetNotFoundError",
    "CatalogError",
    "DownloadError",
    "FetchProgress",
    "IntegrityError",
    "MaterializationError",
    "MaterializedVoice",
    "MissingAudioDependencyError",
    "OfflineError",
    "PlaybackError",
    "ResolvedVoice",
    "VoiceEntry",
    "VoiceNotFoundError",
    "VoiceRef",
    "VoicefolioError",
]


@dataclass(frozen=True, slots=True)
class FetchProgress:
    phase: Literal["cache_check", "download", "verify", "ready"]
    ref: str
    completed: int | None = None
    total: int | None = None


@dataclass(frozen=True, slots=True)
class VoiceRef:
    namespace: str
    id: str

    def __post_init__(self) -> None:
        if (
            not self.namespace
            or ":" in self.namespace
            or any(c.isspace() for c in self.namespace)
        ):
            raise ValueError(
                "voice namespace must be non-empty and contain no colon/whitespace"
            )
        if not self.id or self.id.startswith("/") or "\\" in self.id:
            raise ValueError("voice id must be a non-empty relative slash path")
        parts = self.id.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("voice id must not contain empty, '.' or '..' path components")

    @classmethod
    def parse(cls, value: str) -> VoiceRef:
        namespace, sep, voice_id = value.partition(":")
        if not sep:
            raise ValueError("voice reference must be '<namespace>:<id>'")
        return cls(namespace=namespace, id=voice_id)

    def __str__(self) -> str:
        return f"{self.namespace}:{self.id}"


@dataclass(frozen=True, slots=True)
class VoiceEntry:
    ref: VoiceRef
    dataset: str
    variant: str
    format: str
    url: str
    size: int
    sha256: str
    source_repository: str
    source_revision: str
    source_path: str
    license: str
    language: str = "und"
    base_id: str | None = None
    license_note: str | None = None
    license_evidence: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.variant not in {"original", "enhanced", "emotion"}:
            raise CatalogError(f"unsupported variant {self.variant!r} for {self.ref}")
        if not isinstance(self.language, str) or self.language not in {"en", "fr", "und"}:
            raise CatalogError(
                f"unsupported language {self.language!r} for {self.ref}; expected en, fr, or und"
            )
        if self.format.lower() not in {"wav", "flac"}:
            raise CatalogError(f"unsupported audio format {self.format!r} for {self.ref}")
        object.__setattr__(self, "format", self.format.lower())
        if self.size <= 0:
            raise CatalogError(f"size must be positive for {self.ref}")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise CatalogError(f"sha256 must be 64 lowercase hex chars for {self.ref}")
        if not self.source_revision:
            raise CatalogError(f"source_revision is required for {self.ref}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": str(self.ref),
            "id": self.ref.id,
            "dataset": self.dataset,
            "language": self.language,
            "variant": self.variant,
            "base_id": self.base_id,
            "format": self.format,
            "url": self.url,
            "size": self.size,
            "sha256": self.sha256,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
            "source_path": self.source_path,
            "license": self.license,
            "license_note": self.license_note,
            "license_evidence": self.license_evidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ResolvedVoice:
    entry: VoiceEntry
    path: Path

    @property
    def ref(self) -> VoiceRef:
        return self.entry.ref

    @property
    def sha256(self) -> str:
        return self.entry.sha256


@dataclass(frozen=True, slots=True)
class MaterializedVoice:
    """Renderer-ready WAV plus its independently pinned source asset."""

    source: ResolvedVoice
    path: Path
    sha256: str
    recipe: str
    sample_rate: int
    channels: int
    subtype: str

    @property
    def entry(self) -> VoiceEntry:
        return self.source.entry

    @property
    def ref(self) -> VoiceRef:
        return self.source.ref

    @property
    def source_sha256(self) -> str:
        return self.source.sha256
