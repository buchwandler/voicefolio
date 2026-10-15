from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import patch

import pytest

from voicefolio import validate_voice_source
from voicefolio.catalog import Catalog
from voicefolio.integration import managed_reference, resolve_voice_source
from voicefolio.models import IntegrityError, VoiceNotFoundError

REF = "kyutai-tts-voices:voice-donations/0a67"


def _source() -> dict[str, Any]:
    return {
        "kind": "managed_reference",
        "resolver": "voicefolio",
        "value": REF,
        "sha256": "4bd75d0ef0ad3f4e82ac075eab2a132651d2463f83bec210edeeccaf69294886",
        "source_revision": "323332d33f997de8394f24a193e1a76df720e01a",
        "source_repository": "kyutai/tts-voices",
        "source_path": "voice-donations/0a67.wav",
        "license": "CC0-1.0",
        "dataset": "voice-donations",
        "variant": "original",
    }


def test_validate_voice_source_checks_pins_without_fetching() -> None:
    catalog = Catalog.builtin()
    source = _source()
    with patch("voicefolio.integration.fetch") as fetch:
        entry = validate_voice_source(source, catalog=catalog)
    fetch.assert_not_called()
    assert str(entry.ref) == REF


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha256", "0" * 64),
        ("source_format", "flac"),
        ("source_revision", "a" * 40),
        ("source_repository", "other/repo"),
        ("source_path", "voice-zero/other.wav"),
        ("license", "CC-BY-NC-4.0"),
        ("dataset", "other-dataset"),
        ("variant", "enhanced"),
    ],
)
def test_validate_voice_source_rejects_stale_required_and_descriptive_fields(
    field: str, value: str
) -> None:
    source = _source()
    source[field] = value
    with pytest.raises(IntegrityError, match=field):
        validate_voice_source(source, catalog=Catalog.builtin())


def test_validate_voice_source_accepts_absent_descriptive_fields() -> None:
    source = _source()
    for field in ("license", "dataset", "variant"):
        source.pop(field)
    entry = validate_voice_source(source, catalog=Catalog.builtin())
    assert str(entry.ref) == REF


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "reference"),
        ("resolver", "onnxvoice"),
        ("value", ""),
    ],
)
def test_validate_voice_source_rejects_bad_kind_resolver_and_empty_value(
    field: str, value: str
) -> None:
    source = _source()
    source[field] = value
    with pytest.raises(IntegrityError):
        validate_voice_source(source, catalog=Catalog.builtin())


def test_unknown_catalog_ref_is_distinct_from_pin_integrity_errors() -> None:
    source = _source()
    source["value"] = "kyutai-tts-voices:unknown/voice"
    with pytest.raises(VoiceNotFoundError):
        validate_voice_source(source, catalog=Catalog.builtin())


def test_resolve_voice_source_validates_then_passes_progress_to_fetch() -> None:
    source = _source()
    progress = object()
    result = object()
    with patch("voicefolio.integration.fetch", return_value=result) as fetch:
        actual = resolve_voice_source(
            source,
            catalog=Catalog.builtin(),
            cache_dir="cache",
            offline=True,
            progress=progress,  # type: ignore[arg-type]
        )
    assert actual is result
    fetch.assert_called_once_with(
        Catalog.builtin().get(REF),
        cache_dir="cache",
        offline=True,
        progress=progress,
    )


def test_resolve_flac_managed_reference_materializes_with_source_pins() -> None:
    entry = Catalog.builtin().get(REF)
    flac_entry = replace(entry, format="flac", source_path="voice-donations/0a67.flac")
    catalog = Catalog([flac_entry])
    source = managed_reference(REF, catalog=catalog)
    source_progress = object()
    materialization_progress = object()
    result = object()
    with patch("voicefolio.integration.materialize_wav", return_value=result) as materialize:
        actual = resolve_voice_source(
            source,
            catalog=catalog,
            cache_dir="cache",
            offline=True,
            progress=source_progress,  # type: ignore[arg-type]
            materialization_progress=materialization_progress,  # type: ignore[arg-type]
        )
    assert actual is result
    materialize.assert_called_once_with(
        flac_entry,
        cache_dir="cache",
        offline=True,
        progress=materialization_progress,
        source_progress=source_progress,
    )
