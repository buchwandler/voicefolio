from __future__ import annotations

import hashlib
import json
from io import BytesIO

import pytest

from voicefolio.errors import CatalogError
from voicefolio.sources import github


class FakeResponse(BytesIO):
    def __init__(self, payload: bytes, url: str) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}
        self._url = url

    def geturl(self) -> str:
        return self._url


def test_pinned_urls_validate_repository_revision_and_path() -> None:
    commit = "a" * 40
    assert github.raw_url("OwenTyme/voice-zero", commit, "voices/alice.flac") == (
        f"https://raw.githubusercontent.com/OwenTyme/voice-zero/{commit}/voices/alice.flac"
    )
    assert github.blob_url("OwenTyme/voice-zero", commit, "voices/alice.flac") == (
        f"https://github.com/OwenTyme/voice-zero/blob/{commit}/voices/alice.flac"
    )
    for repository in ("owner", "owner/../repo", "https://example.org/repo"):
        with pytest.raises(CatalogError):
            github.raw_url(repository, commit, "voices/alice.flac")
    for path in (
        "../secret.flac",
        "voices/%2e%2e/secret",
        "/absolute.flac",
        "voices\\bad.flac",
    ):
        with pytest.raises(CatalogError):
            github.raw_url("OwenTyme/voice-zero", commit, path)
    with pytest.raises(CatalogError):
        github.raw_url("OwenTyme/voice-zero", "main", "voices/alice.flac")


def test_resolve_revision_and_tree_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    commit = "b" * 40
    calls: list[str] = []

    def open_url(url: str, *, timeout: int = 60) -> FakeResponse:
        del timeout
        calls.append(url)
        if "/commits/main" in url:
            return FakeResponse(json.dumps({"sha": commit}).encode(), url)
        return FakeResponse(json.dumps({"truncated": False, "tree": []}).encode(), url)

    monkeypatch.setattr(github, "_open_url", open_url)
    assert github.resolve_revision("OwenTyme/voice-zero", "main") == commit
    assert github.repository_tree("OwenTyme/voice-zero", commit) == []
    assert len(calls) == 2

    monkeypatch.setattr(
        github,
        "_open_url",
        lambda url, timeout=60: FakeResponse(
            json.dumps({"truncated": True, "tree": []}).encode(), url
        ),
    )
    with pytest.raises(CatalogError, match="truncated"):
        github.repository_tree("OwenTyme/voice-zero", commit)


def test_read_file_is_bounded_and_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    commit = "c" * 40
    url = github.raw_url("OwenTyme/voice-zero", commit, "README.md")
    open_url = github._open_url
    monkeypatch.setattr(
        github,
        "_open_url",
        lambda requested, timeout=60: FakeResponse(b"readme", requested),
    )
    assert (
        github.read_file("OwenTyme/voice-zero", commit, "README.md", max_bytes=6) == b"readme"
    )
    with pytest.raises(CatalogError, match="exceeds"):
        github.read_file("OwenTyme/voice-zero", commit, "README.md", max_bytes=5)
    with pytest.raises(CatalogError, match="HTTPS"):
        open_url(url.replace("https://", "http://"))


def test_streaming_integrity_checks_size_sha256_and_git_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "d" * 40
    path = "voices/alice.flac"
    payload = b"fLaC-test-bytes"
    blob_id = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    monkeypatch.setattr(
        github,
        "_open_url",
        lambda url, timeout=60: FakeResponse(payload, url),
    )
    assert github.file_integrity(
        "OwenTyme/voice-zero",
        commit,
        path,
        expected_size=len(payload),
        expected_blob_id=blob_id,
    ) == (len(payload), hashlib.sha256(payload).hexdigest())
    with pytest.raises(CatalogError, match="Git blob"):
        github.file_integrity(
            "OwenTyme/voice-zero",
            commit,
            path,
            expected_size=len(payload),
            expected_blob_id="e" * 40,
        )
    with pytest.raises(CatalogError, match="size"):
        github.file_integrity(
            "OwenTyme/voice-zero",
            commit,
            path,
            expected_size=len(payload) + 1,
        )
