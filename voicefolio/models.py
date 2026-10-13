from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Mapping


class VoicefolioError(Exception):
    """Base error for public Voicefolio failures."""


class CatalogError(VoicefolioError):
    """Catalog data is malformed or inconsistent."""


class VoiceNotFoundError(VoicefolioError):
    """A stable voice reference is not present in the active catalog."""


class IntegrityError(VoicefolioError):
    """Downloaded or exported audio does not match its catalog pin."""


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
    base_id: str | None = None
    license_note: str | None = None
    license_evidence: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.variant not in {"original", "enhanced"}:
            raise CatalogError(f"unsupported variant {self.variant!r} for {self.ref}")
        if self.format.lower() != "wav":
            raise CatalogError(f"MVP supports WAV catalog assets only: {self.ref}")
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
