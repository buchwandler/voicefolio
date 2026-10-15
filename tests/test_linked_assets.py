from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from voicefolio.errors import AssetNotFoundError, CatalogError, IntegrityError, OfflineError
from voicefolio.linked_assets import (
    PinnedLinkedAsset,
    fetch_linked_asset,
    linked_asset_path,
)
from voicefolio.models import VoiceEntry, VoiceRef


def _entry(source: Path, payload: bytes) -> VoiceEntry:
    return VoiceEntry(
        ref=VoiceRef("fine-read-it-voices", "F002"),
        dataset="fine-read-it-voices",
        language="en",
        variant="original",
        format="wav",
        url="https://example.invalid/reference.wav",
        size=123,
        sha256="a" * 64,
        source_repository="zloezlo/fine-read-it-voices",
        source_revision="c" * 40,
        source_path="F002.wav",
        license="CC-BY-4.0",
        metadata={
            "preview_demo": {
                "kind": "synthesized_demo",
                "format": "wav",
                "url": source.as_uri(),
                "path": "samples/F002.wav",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        },
    )


def test_fetch_linked_asset_is_verified_cached_and_format_preserving(tmp_path: Path) -> None:
    payload = b"separate synthesized demo bytes"
    source = tmp_path / "source-demo.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)

    resolved = fetch_linked_asset(entry, "preview_demo", cache_dir=tmp_path / "cache")
    expected_path = linked_asset_path(resolved.asset, tmp_path / "cache")
    assert resolved.path == expected_path
    assert resolved.path.suffix == ".wav"
    assert resolved.path.read_bytes() == payload
    assert resolved.asset.kind == "synthesized_demo"
    assert resolved.asset.path == "samples/F002.wav"
    assert (
        fetch_linked_asset(
            entry,
            "preview_demo",
            cache_dir=tmp_path / "cache",
            offline=True,
        )
        == resolved
    )


def test_fetch_linked_asset_offline_miss_and_corrupt_download_fail_closed(
    tmp_path: Path,
) -> None:
    payload = b"demo bytes"
    source = tmp_path / "source-demo.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)
    cache_dir = tmp_path / "cache"

    with pytest.raises(OfflineError, match="not cached"):
        fetch_linked_asset(entry, "preview_demo", cache_dir=cache_dir, offline=True)

    broken_metadata = dict(entry.metadata["preview_demo"])
    broken_metadata["sha256"] = "f" * 64
    broken_entry = replace(entry, metadata={"preview_demo": broken_metadata})
    with pytest.raises(IntegrityError, match="SHA-256 mismatch"):
        fetch_linked_asset(broken_entry, "preview_demo", cache_dir=cache_dir)
    assert not linked_asset_path(
        PinnedLinkedAsset.from_entry(broken_entry, "preview_demo"), cache_dir
    ).exists()


def test_linked_asset_rejects_missing_metadata_and_unsafe_pins(tmp_path: Path) -> None:
    payload = b"demo"
    source = tmp_path / "source-demo.wav"
    source.write_bytes(payload)
    entry = _entry(source, payload)
    entry_without_demo = VoiceEntry(
        ref=entry.ref,
        dataset=entry.dataset,
        language=entry.language,
        variant=entry.variant,
        format=entry.format,
        url=entry.url,
        size=entry.size,
        sha256=entry.sha256,
        source_repository=entry.source_repository,
        source_revision=entry.source_revision,
        source_path=entry.source_path,
        license=entry.license,
    )
    with pytest.raises(AssetNotFoundError, match="no linked asset"):
        fetch_linked_asset(entry_without_demo, "preview_demo", cache_dir=tmp_path / "cache")

    valid = PinnedLinkedAsset.from_entry(entry, "preview_demo")
    with pytest.raises(CatalogError, match="traversal"):
        PinnedLinkedAsset(
            valid.kind,
            valid.format,
            valid.url,
            "samples/%252e%252e/escape.wav",
            valid.size,
            valid.sha256,
        )
    with pytest.raises(CatalogError, match="extension"):
        PinnedLinkedAsset(
            valid.kind, valid.format, valid.url, "samples/demo.flac", valid.size, valid.sha256
        )
