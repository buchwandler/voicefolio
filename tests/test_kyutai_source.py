from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from voicefolio import cli
from voicefolio.catalog import Catalog
from voicefolio.models import CatalogError
from voicefolio.sources import huggingface
from voicefolio.sources.kyutai_tts_voices import (
    DEFAULT_REPOSITORY,
    NAMESPACE,
    build_catalog,
    discover_snapshot,
    load_license_policy,
    resolve_license,
    verify_kyutai_catalog,
)

REVISION = "a" * 40
NEW_REVISION = "b" * 40


def _row(
    voice_id: str,
    *,
    revision: str = REVISION,
    sha256: str | None = None,
    **changes: Any,
) -> dict[str, Any]:
    path = f"{voice_id}.wav"
    license_name, license_note = resolve_license(path)
    row: dict[str, Any] = {
        "id": voice_id,
        "dataset": voice_id.split("/", 1)[0],
        "variant": "enhanced" if voice_id.endswith("_enhanced") else "original",
        "base_id": voice_id.removesuffix("_enhanced")
        if voice_id.endswith("_enhanced")
        else None,
        "format": "wav",
        "url": huggingface.resolve_url(DEFAULT_REPOSITORY, revision, path),
        "size": 123,
        "sha256": sha256 or hashlib.sha256(voice_id.encode()).hexdigest(),
        "source_repository": DEFAULT_REPOSITORY,
        "source_revision": revision,
        "source_path": path,
        "license": license_name,
        "license_note": license_note,
        "license_evidence": huggingface.blob_url(DEFAULT_REPOSITORY, revision, "README.md"),
        "metadata": {},
    }
    row.update(changes)
    return row


def _snapshot(rows: list[dict[str, Any]], *, revision: str = REVISION) -> dict[str, Any]:
    return {
        "schema": 1,
        "kind": "voicefolio-catalog",
        "namespace": NAMESPACE,
        "source": {
            "provider": "huggingface",
            "repository": DEFAULT_REPOSITORY,
            "requested_revision": "main",
            "revision": revision,
            "prompt_count": len(rows),
            "license": "mixed",
        },
        "voices": sorted(copy.deepcopy(rows), key=lambda row: row["id"]),
    }


def test_packaged_catalog_preserves_every_migrated_pocket_id_and_digest() -> None:
    baseline_path = Path(__file__).parent / "fixtures" / "kyutai-voice-baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected = {voice_id: sha256 for voice_id, sha256 in baseline}
    actual = {
        entry.ref.id: entry.sha256
        for entry in Catalog.builtin().list(namespace=NAMESPACE)
    }
    assert len(actual) >= len(expected)
    for voice_id, expected_sha256 in expected.items():
        assert actual[voice_id] == expected_sha256


def test_synthetic_append_preserves_baseline_and_validates_as_1162_voices(
    tmp_path: Path,
) -> None:
    packaged_path = Path(__file__).parents[1] / "voicefolio/resources/catalogs/kyutai-tts-voices.json"
    baseline = json.loads(packaged_path.read_text(encoding="utf-8"))
    discovered = copy.deepcopy(baseline)
    appended = copy.deepcopy(
        next(row for row in baseline["voices"] if row["id"] == "voice-donations/0a67")
    )
    appended["id"] = "voice-donations/__synthetic_append__"
    appended["source_path"] = f"{appended['id']}.wav"
    appended["url"] = huggingface.resolve_url(
        appended["source_repository"],
        appended["source_revision"],
        appended["source_path"],
    )
    discovered["voices"].append(appended)
    discovered["voices"].sort(key=lambda row: row["id"])
    discovered["source"]["prompt_count"] = len(discovered["voices"])

    result = build_catalog(baseline, discovered_snapshot=discovered)
    verify_kyutai_catalog(result)
    expected = {row["id"]: row["sha256"] for row in baseline["voices"]}
    actual = {row["id"]: row["sha256"] for row in result["voices"]}
    assert len(actual) == 1162
    assert all(actual[voice_id] == sha256 for voice_id, sha256 in expected.items())
    assert "voice-donations/__synthetic_append__" in actual

    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(result), encoding="utf-8")
    validation = CliRunner().invoke(
        cli.app, ["validate", "--catalog", str(candidate_path)]
    )
    assert validation.exit_code == 0, validation.output
    assert validation.output.strip() == "ok: 1162 voices"



def test_license_policy_keeps_override_and_fails_closed() -> None:
    policy = load_license_policy()
    assert {rule["license"] for rule in policy["rules"]} == {
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-NC-4.0",
    }
    assert resolve_license("unmute-prod-website/other.wav") == (
        "CC0-1.0",
        "Upstream README describes most unmute-prod-website prompts as Kyutai recordings usable as CC0.",
    )
    assert resolve_license("unmute-prod-website/degaulle-2.wav") == (
        "NOASSERTION",
        "Upstream README does not establish a definitive license for this file.",
    )
    with pytest.raises(CatalogError, match="no unique license rule"):
        resolve_license("unknown-collection/voice.wav")


def test_license_override_wins_and_ambiguous_prefixes_fail() -> None:
    policy = load_license_policy()
    policy["rules"].append(
        {
            "prefix": "unmute-prod-website/",
            "license": "CC-BY-4.0",
            "license_note": None,
        }
    )
    assert resolve_license("unmute-prod-website/degaulle-2.wav", policy)[0] == "NOASSERTION"
    with pytest.raises(CatalogError, match="multiple unique license rule"):
        resolve_license("unmute-prod-website/another.wav", policy)


def test_file_integrity_uses_tree_metadata_without_download() -> None:
    expected_sha = "c" * 64
    with patch("voicefolio.sources.huggingface._read_url") as read_url:
        assert huggingface.file_integrity(
            DEFAULT_REPOSITORY,
            REVISION,
            "voice-zero/a.wav",
            {"size": 21, "lfs": {"oid": expected_sha}},
        ) == (21, expected_sha)
    read_url.assert_not_called()


def test_file_integrity_downloads_only_when_metadata_is_incomplete() -> None:
    payload = b"wav contents"
    expected = (len(payload), hashlib.sha256(payload).hexdigest())
    with patch("voicefolio.sources.huggingface._read_url", return_value=payload) as read_url:
        assert (
            huggingface.file_integrity(
                DEFAULT_REPOSITORY,
                REVISION,
                "voice-zero/a.wav",
                {"size": len(payload)},
            )
            == expected
        )
    read_url.assert_called_once_with(
        huggingface.resolve_url(DEFAULT_REPOSITORY, REVISION, "voice-zero/a.wav")
    )


def test_discovery_filters_wavs_pins_metadata_and_sorts() -> None:
    paths = [
        "voice-zero/person_enhanced.wav",
        "README.md",
        "voice-zero/person.wav",
        "voice-zero/embedding.safetensors",
        "ears/sample.wav",
    ]
    tree = [{"path": path, "size": len(path), "lfs": {"oid": "d" * 64}} for path in paths]
    with (
        patch("voicefolio.sources.kyutai_tts_voices.resolve_revision", return_value=REVISION),
        patch("voicefolio.sources.kyutai_tts_voices.repository_tree", return_value=tree),
        patch(
            "voicefolio.sources.kyutai_tts_voices.file_integrity",
            side_effect=lambda _repo, _rev, path, _meta: (
                len(path),
                hashlib.sha256(path.encode()).hexdigest(),
            ),
        ),
    ):
        catalog = discover_snapshot()
    rows = catalog["voices"]
    assert [row["id"] for row in rows] == [
        "ears/sample",
        "voice-zero/person",
        "voice-zero/person_enhanced",
    ]
    enhanced = rows[-1]
    assert enhanced["variant"] == "enhanced"
    assert enhanced["base_id"] == "voice-zero/person"
    assert enhanced["source_revision"] == REVISION
    assert f"/resolve/{REVISION}/" in enhanced["url"]
    assert enhanced["license_evidence"] == (
        f"https://huggingface.co/{DEFAULT_REPOSITORY}/blob/{REVISION}/README.md"
    )
    assert catalog["source"]["prompt_count"] == 3


def test_verify_allows_historical_entry_revision() -> None:
    historical = _row("voice-donations/a", revision=REVISION)
    catalog = _snapshot([historical], revision=NEW_REVISION)
    verify_kyutai_catalog(catalog)


def test_build_preserves_same_digest_row_exactly_and_keeps_removed_paths() -> None:
    old_a = _row("voice-donations/a", revision=REVISION, sha256="1" * 64)
    old_a["metadata"] = {"legacy": "keep exactly"}
    old_b = _row("voice-donations/b", revision=REVISION, sha256="2" * 64)
    previous = _snapshot([old_a, old_b], revision=REVISION)
    scanned_a = _row("voice-donations/a", revision=NEW_REVISION, sha256="1" * 64)
    discovered = _snapshot([scanned_a], revision=NEW_REVISION)

    result = build_catalog(previous, discovered_snapshot=discovered)

    assert result["source"]["revision"] == NEW_REVISION
    assert result["voices"] == [old_a, old_b]
    assert result["voices"][0]["source_revision"] == REVISION


def test_build_rejects_changed_bytes_for_published_id() -> None:
    previous = _snapshot([_row("voice-donations/a", sha256="1" * 64)])
    discovered = _snapshot(
        [_row("voice-donations/a", revision=NEW_REVISION, sha256="2" * 64)],
        revision=NEW_REVISION,
    )
    with pytest.raises(CatalogError, match="Stable voice ref collision"):
        build_catalog(previous, discovered_snapshot=discovered)


def test_build_appends_new_ids_in_sorted_order_and_is_deterministic() -> None:
    previous = _snapshot([_row("voice-donations/z", sha256="1" * 64)])
    discovered = _snapshot(
        [
            _row("voice-donations/z", revision=NEW_REVISION, sha256="1" * 64),
            _row("voice-donations/a", revision=NEW_REVISION, sha256="2" * 64),
        ],
        revision=NEW_REVISION,
    )
    first = build_catalog(previous, discovered_snapshot=discovered)
    second = build_catalog(previous, discovered_snapshot=discovered)
    assert [row["id"] for row in first["voices"]] == [
        "voice-donations/a",
        "voice-donations/z",
    ]
    assert first["voices"][0]["source_revision"] == NEW_REVISION
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_path", "../unsafe.wav", "unsafe path component"),
        ("format", "mp3", "format must be 'wav'"),
        ("size", 0, "positive integer"),
        ("sha256", "A" * 64, "lowercase hexadecimal"),
        ("source_revision", "main", "lowercase 40-character"),
        ("license_evidence", "https://example.invalid/README.md", "pinned README"),
    ],
)
def test_maintainer_verifier_rejects_invalid_rows(field: str, value: Any, message: str) -> None:
    row = _row("voice-donations/a")
    row[field] = value
    with pytest.raises(CatalogError, match=message):
        verify_kyutai_catalog(_snapshot([row]))


def test_maintainer_verifier_rejects_unsorted_rows_and_missing_enhanced_base() -> None:
    unsorted = _snapshot([_row("voice-donations/z"), _row("voice-donations/a")])
    unsorted["voices"].reverse()
    with pytest.raises(CatalogError, match="sorted"):
        verify_kyutai_catalog(unsorted)

    enhanced = _row("voice-zero/person_enhanced")
    with pytest.raises(CatalogError, match="missing its original base"):
        verify_kyutai_catalog(_snapshot([enhanced]))
