from __future__ import annotations

import hashlib
import io
import json
from typing import Any
from unittest.mock import patch

import pytest

from voicefolio.errors import CatalogError
from voicefolio.sources import huggingface

REPOSITORY = "zloezlo/fine-read-it-voices"
REVISION = "a" * 40


class _Response:
    def __init__(self, payload: bytes, link: str = "") -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {"Link": link}

    def __enter__(self) -> _Response:  # noqa: PYI034
        return self

    def __exit__(self, *_args: object) -> None:
        self._stream.close()

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _entry(path: str, kind: str) -> dict[str, str]:
    return {"type": kind, "path": path}


@pytest.mark.parametrize(
    ("repo_kind", "repository", "api_namespace"),
    [("model", "kyutai/tts-voices", "models"), ("dataset", REPOSITORY, "datasets")],
)
def test_revision_resolution_uses_configured_repository_api(
    repo_kind: huggingface.HuggingFaceRepoKind, repository: str, api_namespace: str
) -> None:
    payload = json.dumps({"sha": REVISION}).encode()
    with patch("voicefolio.sources.huggingface._read_url", return_value=payload) as read_url:
        assert huggingface.resolve_revision(repository, "main", repo_kind=repo_kind) == REVISION
    read_url.assert_called_once_with(
        f"https://huggingface.co/api/{api_namespace}/{repository}/revision/main"
    )


@pytest.mark.parametrize(
    ("repo_kind", "repository", "api_namespace"),
    [("model", "kyutai/tts-voices", "models"), ("dataset", REPOSITORY, "datasets")],
)
def test_repository_tree_uses_configured_repository_api(
    repo_kind: huggingface.HuggingFaceRepoKind, repository: str, api_namespace: str
) -> None:
    with patch(
        "voicefolio.sources.huggingface.urllib.request.urlopen",
        return_value=_Response(b"[]"),
    ) as open_url:
        assert huggingface.repository_tree(repository, REVISION, repo_kind=repo_kind) == []
    request = open_url.call_args.args[0]
    assert request.full_url == (
        f"https://huggingface.co/api/{api_namespace}/{repository}/tree/{REVISION}"
        "?recursive=true&expand=true"
    )


def test_repository_api_rejects_unknown_kind() -> None:
    with pytest.raises(CatalogError, match="repo_kind"):
        huggingface._api_namespace("unknown")


def test_read_file_uses_pinned_raw_path_and_size_limit() -> None:
    with patch("voicefolio.sources.huggingface._read_url", return_value=b"metadata") as read:
        assert (
            huggingface.read_file(REPOSITORY, REVISION, "pool.json", max_bytes=123)
            == b"metadata"
        )
    read.assert_called_once_with(
        f"https://huggingface.co/datasets/{REPOSITORY}/raw/{REVISION}/pool.json",
        max_bytes=123,
    )


def test_repository_tree_follows_directory_paths_and_same_path_pagination() -> None:
    root_path = f"https://huggingface.co/api/datasets/{REPOSITORY}/tree/{REVISION}"
    root = f"{root_path}?recursive=true&expand=true"
    second_root_page = f"{root_path}?cursor=next"
    samples = f"{root_path}/samples?recursive=true&expand=true"
    nested = f"{root_path}/samples/nested?recursive=true&expand=true"
    pages = {
        root: _Response(
            json.dumps(
                [
                    _entry("samples", "directory"),
                    _entry("samples/F002.wav", "file"),
                ]
            ).encode(),
            f'<{second_root_page}>; rel="next"',
        ),
        second_root_page: _Response(json.dumps([_entry("pool.json", "file")]).encode()),
        samples: _Response(
            json.dumps(
                [
                    {
                        "type": "file",
                        "path": "samples/F002.wav",
                        "securityFileStatus": {"status": "safe"},
                    },
                    _entry("samples/nested", "directory"),
                ]
            ).encode()
        ),
        nested: _Response(json.dumps([_entry("samples/nested/demo.wav", "file")]).encode()),
    }

    def open_url(request: Any, *, timeout: int) -> _Response:
        del timeout
        url = request.full_url
        if url not in pages:
            raise AssertionError(f"unexpected tree URL: {url}")
        return pages[url]

    with patch("voicefolio.sources.huggingface.urllib.request.urlopen", side_effect=open_url):
        result = huggingface.repository_tree(REPOSITORY, REVISION, repo_kind="dataset")

    assert [row["path"] for row in result] == [
        "pool.json",
        "samples",
        "samples/F002.wav",
        "samples/nested",
        "samples/nested/demo.wav",
    ]
    assert result[2]["securityFileStatus"] == {"status": "safe"}


def test_repository_tree_rejects_external_pagination_links() -> None:
    response = _Response(
        json.dumps([_entry("README.md", "file")]).encode(),
        '<https://evil.example/steal>; rel="next"',
    )
    with (
        patch("voicefolio.sources.huggingface.urllib.request.urlopen", return_value=response),
        pytest.raises(CatalogError, match="same-origin"),
    ):
        huggingface.repository_tree(REPOSITORY, REVISION, repo_kind="dataset")


def test_repository_tree_rejects_malformed_entries() -> None:
    response = _Response(json.dumps([{"type": "file"}]).encode())
    with (
        patch("voicefolio.sources.huggingface.urllib.request.urlopen", return_value=response),
        pytest.raises(CatalogError, match="no path"),
    ):
        huggingface.repository_tree(REPOSITORY, REVISION, repo_kind="dataset")


def test_stream_audio_integrity_is_incremental_and_rejects_pointer_or_oversize() -> None:
    payload = b"RIFF" + b"voice audio"
    with patch(
        "voicefolio.sources.huggingface.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        assert huggingface._stream_url_integrity("https://example.invalid/audio") == (
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )

    pointer = b"version https://git-lfs.github.com/spec/v1\n" + b"x" * 80
    with (
        patch(
            "voicefolio.sources.huggingface.urllib.request.urlopen",
            return_value=_Response(pointer),
        ),
        pytest.raises(CatalogError, match="LFS pointer"),
    ):
        huggingface._stream_url_integrity("https://example.invalid/audio")

    with (
        patch(
            "voicefolio.sources.huggingface.urllib.request.urlopen",
            return_value=_Response(b"123456"),
        ),
        pytest.raises(CatalogError, match="byte limit"),
    ):
        huggingface._stream_url_integrity("https://example.invalid/audio", max_bytes=5)


@pytest.mark.parametrize(
    "path",
    ["../outside.wav", "/absolute.wav", "folder/%252e%252e/outside.wav", "folder\\evil.wav"],
)
def test_source_asset_paths_reject_traversal(path: str) -> None:
    with pytest.raises(CatalogError):
        huggingface.resolve_url(REPOSITORY, REVISION, path)
