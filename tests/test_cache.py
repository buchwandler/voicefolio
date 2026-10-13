import hashlib
from pathlib import Path

from voicefolio.cache import fetch
from voicefolio.models import VoiceEntry, VoiceRef


def test_fetch_verifies_file_url(tmp_path: Path):
    payload = b"RIFF-not-a-real-wav-but-integrity-is-testable"
    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    entry = VoiceEntry(
        ref=VoiceRef.parse("test:voice"),
        dataset="test",
        variant="original",
        format="wav",
        url=source.resolve().as_uri(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source_repository="local/test",
        source_revision="rev1",
        source_path="source.wav",
        license="CC0-1.0",
    )
    resolved = fetch(entry, cache_dir=tmp_path / "cache")
    assert resolved.path.read_bytes() == payload
    assert resolved.sha256 == entry.sha256
