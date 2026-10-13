import pytest

from voicefolio.catalog import Catalog
from voicefolio.models import CatalogError, VoiceEntry, VoiceRef


def test_builtin_catalog_has_complete_pinned_kyutai_snapshot():
    catalog = Catalog.builtin()
    kyutai = catalog.list(namespace="kyutai-tts-voices")
    assert len(kyutai) == 1161
    assert {entry.dataset for entry in kyutai} == {
        "alba-mackenna",
        "cml-tts",
        "ears",
        "expresso",
        "unmute-prod-website",
        "vctk",
        "voice-donations",
        "voice-zero",
    }

    legacy_hashes = {
        "alba-mackenna/a-moment-by": "a1805f0e3610f0d5985f4abb51979620a012899e810019960310944bbcba509d",
        "alba-mackenna/announcer": "e8b55193435db043833dda62fb759ee2779ace195811340ee8d28c7c4a4ccc24",
        "ears/p001/freeform_speech_01": "beef9034c42a40a5696657cfd39f01d56243e3ca215d0b1c0269e88b6ac08b33",
        "ears/p001/freeform_speech_01_enhanced": "6a0d52e5de3469f659a903dd0db8113d624b88da603b5452f37dd80dccc86753",
        "expresso/ex01-ex02_default_001_channel1_168s": "7e196b0f345e11f4d54fbcf4376b3f1f845837f5122f7dd2e1c040410ec3c3c8",
        "expresso/ex01-ex02_default_001_channel2_198s": "c6e3c024bfa1975d4a6cc86907e589ccfac2de661ce54711bace7f79455e0b93",
        "vctk/p225_023": "4f15f804be0f437912697ffaa56b03759e10b5e1db82fcdac20412fe95bedec9",
        "vctk/p225_023_enhanced": "10d947a5f12cc0f3b009a91d8b22c2f9e4ecd3c42d9f63ecfbe5b8facb74004c",
        "voice-donations/0a67": "4bd75d0ef0ad3f4e82ac075eab2a132651d2463f83bec210edeeccaf69294886",
        "voice-donations/0a67_enhanced": "f3d11f89eb6ee77ca0ab1ceed734755d0fff3d2791050cb4fe20428e0f6a76b3",
        "voice-zero/bill_boerst": "be4815e4fb760ba1b78117545a260cce4a4c124c7657bc5c6127a0fef8ba661f",
        "voice-zero/caro_davy": "40c692c005a0268a7a5b6ebae348077d3dca6a86eb6b12bd36e343bbcd71b5f6",
    }
    for voice_id, expected_sha256 in legacy_hashes.items():
        assert catalog.get(f"kyutai-tts-voices:{voice_id}").sha256 == expected_sha256

    assert (
        catalog.get("kyutai-tts-voices:voice-zero/peter_yearsley").sha256
        == "fbb3920fda7ae26a5a8b317ffcae1d55c0bd5d89d075205f5a52b1e924b83f51"
    )
    assert (
        catalog.get("kyutai-tts-voices:voice-zero/stuart_bell").sha256
        == "00c7baeb2fb7a8c1c6198e045b5e853a7ccc04002a51a09b4be3dd7c96994f73"
    )
    assert {
        entry.ref.id
        for entry in catalog.list(namespace="kyutai-tts-voices", dataset="voice-zero")
    } == {
        "voice-zero/bill_boerst",
        "voice-zero/caro_davy",
        "voice-zero/peter_yearsley",
        "voice-zero/stuart_bell",
    }
    assert all(f"/resolve/{entry.source_revision}/" in entry.url for entry in kyutai)
    assert all(
        entry.license_evidence is None
        or f"/blob/{entry.source_revision}/" in entry.license_evidence
        for entry in kyutai
    )


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
