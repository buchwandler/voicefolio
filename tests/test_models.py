import pytest

from voicefolio.models import VoiceRef


def test_voice_ref_roundtrip():
    ref = VoiceRef.parse("kyutai-tts-voices:voice-donations/0a67")
    assert ref.namespace == "kyutai-tts-voices"
    assert ref.id == "voice-donations/0a67"
    assert str(ref) == "kyutai-tts-voices:voice-donations/0a67"


@pytest.mark.parametrize("value", ["missing-colon", "x:/abs", "x:a//b", "x:a/../b"])
def test_invalid_voice_refs(value):
    with pytest.raises(ValueError):
        VoiceRef.parse(value)
