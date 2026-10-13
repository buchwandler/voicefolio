import pytest

from voicefolio.catalog import Catalog
from voicefolio.models import CatalogError, VoiceEntry, VoiceRef


def test_builtin_catalog_has_stable_sample_refs():
    catalog = Catalog.builtin()
    assert len(catalog) >= 8
    entry = catalog.get("kyutai-tts-voices:voice-donations/0a67")
    assert entry.license == "CC0-1.0"
    assert entry.sha256 == "4bd75d0ef0ad3f4e82ac075eab2a132651d2463f83bec210edeeccaf69294886"


def test_duplicate_ref_with_different_digest_is_rejected():
    common = {
        "ref": VoiceRef.parse("test:a"),
        "dataset": "x",
        "variant": "original",
        "format": "wav",
        "url": "https://example.invalid/a.wav",
        "size": 1,
        "source_repository": "x/y",
        "source_revision": "r",
        "source_path": "a.wav",
        "license": "CC0-1.0",
    }
    first = VoiceEntry(sha256="0" * 64, **common)
    second = VoiceEntry(sha256="1" * 64, **common)
    with pytest.raises(CatalogError):
        Catalog([first, second])
