import pytest

from voicefolio.models import CatalogError, VoiceEntry, VoiceRef


def test_voice_ref_roundtrip():
    ref = VoiceRef.parse("kyutai-tts-voices:voice-donations/0a67")
    assert ref.namespace == "kyutai-tts-voices"
    assert ref.id == "voice-donations/0a67"
    assert str(ref) == "kyutai-tts-voices:voice-donations/0a67"


@pytest.mark.parametrize("value", ["missing-colon", "x:/abs", "x:a//b", "x:a/../b"])
def test_invalid_voice_refs(value):
    with pytest.raises(ValueError):
        VoiceRef.parse(value)


def _entry(language: str = "und") -> VoiceEntry:
    return VoiceEntry(
        ref=VoiceRef.parse("test:voice"),
        dataset="test",
        variant="original",
        format="wav",
        url="https://example.invalid/voice.wav",
        size=1,
        sha256="0" * 64,
        source_repository="test/voices",
        source_revision="revision",
        source_path="voice.wav",
        license="CC0-1.0",
        language=language,
    )


def test_voice_entry_defaults_language_to_und_and_serializes_it():
    entry = _entry()

    assert entry.language == "und"
    assert entry.to_dict()["language"] == "und"


@pytest.mark.parametrize("language", ["en", "fr", "und"])
def test_voice_entry_serializes_supported_language(language):
    entry = _entry(language)

    assert entry.to_dict()["language"] == language


@pytest.mark.parametrize("language", ["", "English", "EN", "de"])
def test_voice_entry_rejects_unsupported_or_unnormalized_language(language):
    with pytest.raises(CatalogError, match="unsupported language"):
        _entry(language)
