import json
from pathlib import Path

from voicefolio.catalog import Catalog
from voicefolio.migration import migrate_pocket_catalog


def test_migrate_preserves_prompt_id_and_digest(tmp_path: Path):
    source = tmp_path / "voice-prompts.json"
    source.write_text(
        json.dumps(
            {
                "schema": 1,
                "kind": "pocket-voice-prompt-catalog",
                "source": {"repository": "kyutai/tts-voices"},
                "prompts": [
                    {
                        "id": "voice-donations/abcd",
                        "dataset": "voice-donations",
                        "variant": "original",
                        "base_id": None,
                        "format": "wav",
                        "url": "https://example.invalid/a.wav",
                        "size": 12,
                        "sha256": "a" * 64,
                        "source_repository": "kyutai/tts-voices",
                        "source_revision": "r1",
                        "source_path": "voice-donations/abcd.wav",
                        "license": "CC0-1.0",
                        "license_note": None,
                        "license_evidence": None,
                        "metadata": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "catalog.json"
    migrate_pocket_catalog(source, dest)
    catalog = Catalog.from_paths([dest])
    entry = catalog.get("kyutai-tts-voices:voice-donations/abcd")
    assert entry.sha256 == "a" * 64
