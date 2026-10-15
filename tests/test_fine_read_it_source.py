from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from voicefolio.errors import CatalogError
from voicefolio.sources import fine_read_it_voices as source

REVISION = "a" * 40
REPOSITORY = source.DEFAULT_REPOSITORY


def _pool() -> list[dict[str, Any]]:
    return [
        {
            "id": "F002",
            "reader": "Reader Two",
            "gender": "female",
            "band": "mid",
            "f0": 221.5,
            "source": "LibriTTS-R train-clean-100 speaker 22 chapter 900",
            "license": "CC BY 4.0 (LibriTTS-R)",
            "qa": {"snr": 27.4},
        },
        {
            "id": "M001",
            "reader": "Reader One",
            "gender": "male",
            "band": "low",
            "f0": 112.0,
            "source": "LibriTTS-R train-clean-360 speaker 11 chapter 800",
            "license": "CC BY 4.0 (LibriTTS-R)",
            "qa": {"snr": 25.0},
        },
    ]


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pool: list[dict[str, Any]] | None = None,
    include_transcripts: bool = True,
    attribution: str | None = None,
) -> None:
    rows = _pool() if pool is None else pool
    monkeypatch.setattr(source, "resolve_revision", lambda _repo, _rev: REVISION)

    tree: list[dict[str, Any]] = []
    files: dict[str, bytes] = {"pool.json": json.dumps(rows).encode()}
    if attribution is None:
        attribution = (
            "F002: Reader Two — LibriTTS-R, CC BY 4.0\nM001: Reader One — LibriTTS-R, CC BY 4.0"
        )
    files["ATTRIBUTION.txt"] = attribution.encode()
    for row in rows:
        voice_id = row["id"]
        for path in (f"{voice_id}.wav", f"samples/{voice_id}.wav"):
            tree.append({"type": "file", "path": path, "size": 15})
        if include_transcripts:
            text_path = f"{voice_id}.txt"
            tree.append({"type": "file", "path": text_path, "size": 12})
            files[text_path] = f"Transcript for {voice_id}.".encode()
    monkeypatch.setattr(source, "repository_tree", lambda _repo, _rev: tree)

    def read_file(_repo: str, _rev: str, path: str, *, max_bytes: int) -> bytes:
        del max_bytes
        return files[path]

    def file_integrity(
        _repo: str,
        _rev: str,
        path: str,
        _metadata: dict[str, Any],
        *,
        dataset: bool,
    ) -> tuple[int, str]:
        assert dataset
        return (15, f"{sum(path.encode()):064x}")

    monkeypatch.setattr(source, "read_file", read_file)
    monkeypatch.setattr(source, "file_integrity", file_integrity)


def test_fine_read_it_builder_builds_deterministic_catalog_and_separate_demo() -> None:
    # This test uses patched upstream transport; production catalogs are pinned separately.
    from pytest import MonkeyPatch

    with MonkeyPatch.context() as monkeypatch:
        _install_source(monkeypatch)
        catalog = source.build_catalog(bootstrap=True)
        assert [row["id"] for row in catalog["voices"]] == ["F002", "M001"]
        row = catalog["voices"][0]
        metadata = row["metadata"]
        assert metadata["speaker_id"] == "22"
        assert metadata["source_subset"] == "LibriTTS-R train-clean-100"
        assert metadata["transcript"] == "Transcript for F002."
        assert row["license"] == "CC-BY-4.0"
        assert metadata["reader"] == "Reader Two"
        assert metadata["preview_demo"]["path"] == "samples/F002.wav"
        assert metadata["preview_demo"]["sha256"] != row["sha256"]
        assert source.build_catalog(bootstrap=True) == catalog
        source.verify_fine_read_it_catalog(catalog)


def test_fine_read_it_builder_requires_explicit_bootstrap() -> None:
    with pytest.raises(CatalogError, match="explicit bootstrap"):
        source.build_catalog()


def test_bootstrap_cannot_ignore_an_explicit_missing_previous_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(source, "resolve_revision", lambda _repo, _rev: REVISION)
    with pytest.raises(CatalogError, match="previous Fine Read It catalog does not exist"):
        source.build_catalog(tmp_path / "missing.json", bootstrap=True)


def test_fine_read_it_builder_rejects_unmaintained_repository() -> None:
    with pytest.raises(CatalogError, match="repository must be"):
        source.build_catalog(repository="other/project", bootstrap=True)


def test_fine_read_it_immutable_merge_keeps_previous_row_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _install_source(monkeypatch)
    original = source.build_catalog(bootstrap=True)
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps(original), encoding="utf-8")

    changed_pool = deepcopy(_pool())
    changed_pool[0]["reader"] = "Changed upstream reader label"
    _install_source(monkeypatch, pool=changed_pool)
    next_revision = "b" * 40
    monkeypatch.setattr(source, "resolve_revision", lambda _repo, _rev: next_revision)
    result = source.build_catalog(previous, revision="main")

    assert result["source_revision"] == next_revision
    assert result["voices"][0] == original["voices"][0]
    source.verify_fine_read_it_catalog(result)


def test_fine_read_it_rejects_changed_immutable_audio_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _install_source(monkeypatch)
    original = source.build_catalog(bootstrap=True)
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(
        source,
        "file_integrity",
        lambda _repo, _rev, _path, _metadata, *, dataset=False: (15, "f" * 64),
    )
    with pytest.raises(CatalogError, match="immutable-ref collision"):
        source.build_catalog(previous)


def test_fine_read_it_rejects_duplicate_pool_ids_and_missing_transcripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicated = _pool() + [_pool()[0]]
    _install_source(monkeypatch, pool=duplicated)
    with pytest.raises(CatalogError, match="duplicate id"):
        source.build_catalog(bootstrap=True)

    _install_source(monkeypatch, include_transcripts=False)
    with pytest.raises(CatalogError, match="transcripts missing"):
        source.build_catalog(bootstrap=True)


def test_fine_read_it_rejects_unknown_license_and_malformed_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _pool()
    rows[0]["license"] = "unknown"
    _install_source(monkeypatch, pool=rows)
    with pytest.raises(CatalogError, match="license is not verified"):
        source.build_catalog(bootstrap=True)

    _install_source(monkeypatch, attribution="F002: duplicate\nF002: duplicate\nM001: valid")
    with pytest.raises(CatalogError, match="repeats id"):
        source.build_catalog(bootstrap=True)


def test_fine_read_it_verifier_rejects_reference_demo_interchange() -> None:
    from pytest import MonkeyPatch

    with MonkeyPatch.context() as monkeypatch:
        _install_source(monkeypatch)
        catalog = source.build_catalog(bootstrap=True)
    broken = deepcopy(catalog)
    broken["voices"][0]["metadata"]["preview_demo"]["path"] = "F002.wav"
    with pytest.raises(CatalogError, match="demo path"):
        source.verify_fine_read_it_catalog(broken)
    same_hash = deepcopy(catalog)
    same_hash["voices"][0]["metadata"]["preview_demo"]["sha256"] = same_hash["voices"][0][
        "sha256"
    ]
    with pytest.raises(CatalogError, match="demo hash matches reference"):
        source.verify_fine_read_it_catalog(same_hash)


def test_packaged_catalog_matches_exact_first_snapshot_pins() -> None:
    project_root = Path(__file__).parents[1]
    catalog = json.loads(
        (project_root / "voicefolio/resources/catalogs/fine-read-it-voices.json").read_text(
            encoding="utf-8"
        )
    )
    baseline = json.loads(
        (project_root / "tests/fixtures/fine-read-it-baseline.json").read_text(encoding="utf-8")
    )
    source.verify_fine_read_it_catalog(catalog)
    rows = catalog["voices"]
    ids = "\n".join(row["id"] for row in rows).encode()
    pins = "\n".join(
        f"{row['id']}\t{row['sha256']}\t{row['source_revision']}" for row in rows
    ).encode()

    assert len(rows) == baseline["count"]
    assert sum("preview_demo" in row["metadata"] for row in rows) == baseline["demo_count"]
    assert catalog["source_repository"] == baseline["source_repository"]
    assert catalog["source_revision"] == baseline["source_revision"]
    assert hashlib.sha256(ids).hexdigest() == baseline["ids_sha256"]
    assert hashlib.sha256(pins).hexdigest() == baseline["pins_sha256"]
