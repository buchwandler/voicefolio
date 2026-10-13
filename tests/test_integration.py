from voicefolio.catalog import Catalog
from voicefolio.integration import managed_reference


def test_managed_reference_is_portable_and_pinned():
    source = managed_reference(
        "kyutai-tts-voices:voice-donations/0a67", catalog=Catalog.builtin()
    )
    assert source["kind"] == "managed_reference"
    assert source["resolver"] == "voicefolio"
    assert source["value"] == "kyutai-tts-voices:voice-donations/0a67"
    assert source["sha256"].startswith("4bd75d0e")
    assert "path" not in source
    assert set(source) == {
        "kind",
        "resolver",
        "value",
        "sha256",
        "source_revision",
        "source_repository",
        "source_path",
        "license",
        "dataset",
        "variant",
    }
