from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from voicefolio.errors import CatalogError
from voicefolio.sources import voice_zero

REVISION = "a" * 40
_REPO = voice_zero.DEFAULT_REPOSITORY


def _git_blob(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


def _setup_fake_source(
    monkeypatch: pytest.MonkeyPatch,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, bytes]:
    files = {
        "README.md": b"Unless otherwise noted, all files in this repository are under the CC0 license.",
        "LICENSE.md": b"All files in this repository are under the CC0 license.",
        "voices/README.md": (
            b"| Name or Username | File Name | Accent | Source |\n"
            b"| --- | --- | --- | --- |\n"
            b"| [Alice](https://example.org/alice) | alice.flac | American | "
            b"[Sample Story, Track 1](https://example.org/story) |\n"
        ),
        "voices-emotion/README.md": b"These synthetic audio files are created from voices.",
        "voices/alice.flac": b"original-audio-bytes",
        "voices-emotion/alice/calm.flac": b"synthetic-calm-audio",
        "voices-emotion/alice/worried.flac": b"synthetic-worried-audio",
        "voices/bob.flac": b"unattributed-original",
        "voices-emotion/bob/calm.flac": b"unattributed-emotion",
    }
    active_overrides = overrides or {
        "source_repository": _REPO,
        "filename_aliases": {},
        "exclude": {
            "voices/bob.flac": {
                "reason": "Quarantined because the source README has no exact filename row."
            }
        },
    }

    def tree(repository: str, revision: str) -> list[dict[str, Any]]:
        assert repository == _REPO
        assert revision == REVISION
        return [
            {"path": path, "type": "blob", "size": len(payload), "sha": _git_blob(payload)}
            for path, payload in sorted(files.items())
        ]

    def read_file(repository: str, revision: str, path: str, *, max_bytes: int) -> bytes:
        assert repository == _REPO
        assert revision == REVISION
        payload = files[path]
        assert len(payload) <= max_bytes
        return payload

    def file_integrity(
        repository: str,
        revision: str,
        path: str,
        *,
        expected_size: int | None = None,
        expected_blob_id: str | None = None,
    ) -> tuple[int, str]:
        assert repository == _REPO
        assert revision == REVISION
        payload = files[path]
        assert expected_size == len(payload)
        assert expected_blob_id == _git_blob(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(voice_zero, "resolve_revision", lambda repository, revision: REVISION)
    monkeypatch.setattr(voice_zero, "repository_tree", tree)
    monkeypatch.setattr(voice_zero, "read_file", read_file)
    monkeypatch.setattr(voice_zero, "file_integrity", file_integrity)
    monkeypatch.setattr(voice_zero, "load_overrides", lambda: copy.deepcopy(active_overrides))
    return files


def test_build_catalog_preserves_stable_ids_metadata_and_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_fake_source(monkeypatch)
    catalog = voice_zero.build_catalog(bootstrap=True, revision=REVISION)
    rows = {row["id"]: row for row in catalog["voices"]}
    original = rows["voices/alice"]
    emotion = rows["voices-emotion/alice/calm"]

    assert catalog["source_revision"] == REVISION
    assert original["variant"] == "original"
    assert original["base_id"] is None
    assert original["format"] == "flac"
    assert original["language"] == "en"
    assert original["license"] == "CC0-1.0"
    assert original["metadata"]["accent"] == "American"
    assert original["metadata"]["accent_confidence"] == "upstream_unverified"
    assert original["metadata"]["source_blob_id"] == _git_blob(b"original-audio-bytes")
    assert emotion["variant"] == "emotion"
    assert emotion["base_id"] == "voices/alice"
    assert emotion["metadata"]["emotion"] == "calm"
    assert emotion["metadata"]["synthetic"] is True
    assert len(catalog["quarantined"]) == 2
    assert {item["source_path"] for item in catalog["quarantined"]} == {
        "voices/bob.flac",
        "voices-emotion/bob/calm.flac",
    }
    voice_zero.verify_voice_zero_catalog(catalog)


def test_double_build_reuses_exact_pins_and_changed_bytes_collide(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    files = _setup_fake_source(monkeypatch)
    first = voice_zero.build_catalog(bootstrap=True, revision=REVISION)
    previous = tmp_path / "voice-zero.json"
    previous.write_text(json.dumps(first), encoding="utf-8")

    def unexpected_download(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise AssertionError("unchanged pinned source bytes should not be downloaded again")

    monkeypatch.setattr(voice_zero, "file_integrity", unexpected_download)
    second = voice_zero.build_catalog(previous, revision=REVISION)
    assert second == first

    files["voices/alice.flac"] = b"changed-audio-bytes"
    monkeypatch.setattr(
        voice_zero,
        "file_integrity",
        lambda repository, revision, path, **kwargs: (
            len(files[path]),
            hashlib.sha256(files[path]).hexdigest(),
        ),
    )
    with pytest.raises(CatalogError, match="immutable-ref collision"):
        voice_zero.build_catalog(previous, revision=REVISION)


def test_filename_override_is_explicit_and_unknown_attribution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overrides = {
        "source_repository": _REPO,
        "filename_aliases": {
            "voices/alice.flac": {
                "attribution_filename": "alice_old.flac",
                "reason": "Reviewed upstream typo in the audio filename.",
            }
        },
        "exclude": {},
    }
    files = _setup_fake_source(monkeypatch, overrides=overrides)
    files["voices/README.md"] = (
        b"| Name or Username | File Name | Accent | Source |\n"
        b"| --- | --- | --- | --- |\n"
        b"| [Alice](https://example.org/alice) | alice_old.flac | American | "
        b"[Sample Story](https://example.org/story) |\n"
    )
    # Keep only the source paths covered by this policy.
    del files["voices/bob.flac"]
    del files["voices-emotion/bob/calm.flac"]
    catalog = voice_zero.build_catalog(bootstrap=True, revision=REVISION)
    original = next(row for row in catalog["voices"] if row["variant"] == "original")
    assert original["metadata"]["attribution_status"] == "reviewed_filename_override"
    assert original["metadata"]["attribution_filename"] == "alice_old.flac"
    assert (
        original["metadata"]["attribution_override_reason"]
        == overrides["filename_aliases"]["voices/alice.flac"]["reason"]
    )

    files["voices/unknown.flac"] = b"unknown"
    with pytest.raises(CatalogError, match="no exact attribution"):
        voice_zero.build_catalog(bootstrap=True, revision=REVISION)


def test_verifier_rejects_broken_emotion_base_and_unpinned_license_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_fake_source(monkeypatch)
    catalog = voice_zero.build_catalog(bootstrap=True, revision=REVISION)
    broken_link = copy.deepcopy(catalog)
    next(row for row in broken_link["voices"] if row["variant"] == "emotion")["base_id"] = (
        "voices/missing"
    )
    with pytest.raises(CatalogError, match="emotion path/metadata/base"):
        voice_zero.verify_voice_zero_catalog(broken_link)

    broken_evidence = copy.deepcopy(catalog)
    broken_evidence["voices"][0]["license_evidence"] = (
        "https://github.com/OwenTyme/voice-zero/blob/main/LICENSE.md"
    )
    with pytest.raises(CatalogError, match="license evidence"):
        voice_zero.verify_voice_zero_catalog(broken_evidence)


def test_packaged_catalog_matches_pinned_identity_baseline() -> None:
    project_root = Path(__file__).parents[1]
    catalog = json.loads(
        (project_root / "voicefolio/resources/catalogs/voice-zero.json").read_text(
            encoding="utf-8"
        )
    )
    baseline = json.loads(
        (project_root / "tests/fixtures/voice-zero-baseline.json").read_text(encoding="utf-8")
    )
    voice_zero.verify_voice_zero_catalog(catalog)
    rows = catalog["voices"]
    ids = "\n".join(row["id"] for row in rows).encode()
    pins = "\n".join(
        f"{row['id']}\t{row['sha256']}\t{row['source_revision']}" for row in rows
    ).encode()
    originals = [row for row in rows if row["variant"] == "original"]
    emotions = [row for row in rows if row["variant"] == "emotion"]

    assert catalog["source_repository"] == baseline["source_repository"]
    assert catalog["source_revision"] == baseline["source_revision"]
    assert len(rows) == baseline["count"]
    assert len(originals) == baseline["original_count"]
    assert len(emotions) == baseline["emotion_count"]
    assert len(catalog["quarantined"]) == baseline["quarantined_count"]
    assert (
        sum(
            row["metadata"]["attribution_status"] == "reviewed_filename_override"
            for row in originals
        )
        == baseline["filename_override_count"]
    )
    assert hashlib.sha256(ids).hexdigest() == baseline["ids_sha256"]
    assert hashlib.sha256(pins).hexdigest() == baseline["pins_sha256"]
    assert any(
        row["metadata"]["accent"] == "Dutch" and row["language"] == "en" for row in originals
    )
