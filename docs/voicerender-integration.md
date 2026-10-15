# VoiceRender integration

Voicefolio owns the pinned source catalog and managed-reference resolver; VoiceRender retains render planning and engine dispatch. Persisted references contain stable source identity, never machine-local cache paths.

## Preflight and execution

Use metadata-only validation during profile loading or preflight. It checks the catalog pins without downloading audio:

```python
from voicefolio import validate_voice_source

entry = validate_voice_source(request.options["voice_source"])
# entry retains the original source format, SHA-256, revision, and provenance.
```

At execution time, resolve and fetch the verified reference:

```python
from voicefolio import resolve_voice_source

resolved = resolve_voice_source(
    request.options["voice_source"],
    offline=selection.offline,
    progress=on_voice_progress,  # optional FetchProgress callback
)
# resolved.path is a verified renderer-ready WAV.
# resolved.entry and resolved.sha256 identify the pinned source asset.
```

`validate_voice_source()` requires `kind="managed_reference"`, `resolver="voicefolio"`, the catalog ref, source SHA-256, source revision, repository, and path. Persisted optional descriptions such as `license`, `dataset`, `variant`, and `source_format` must match when present. A ref absent from the catalog raises `VoiceNotFoundError`; pin or description mismatches raise `IntegrityError`. Preflight does not fetch and does not require a cache hit.

`resolve_voice_source()` calls the same validator before fetching. WAV sources are returned byte-for-byte. FLAC sources are verified and then materialized to a deterministic WAV using the optional `voicefolio[audio]` extra; the managed reference continues to store the FLAC source digest, never the derived WAV digest. Runtime failures use public `VoicefolioError` subclasses, including actionable errors for missing optional dependencies. Callers should branch on exception types rather than parsing messages.

The optional `FetchProgress` callback reports cache-check, download, verification, and ready phases. Catalog listing, validation, and binding generation are offline and do not initialize the audio backend.

## Persisted identity

The canonical managed-reference fields are:

```toml
[binding.options.voice_source]
kind = "managed_reference"
resolver = "voicefolio"
value = "kyutai-tts-voices:voice-donations/0a67"
sha256 = "4bd75d0ef0ad3f4e82ac075eab2a132651d2463f83bec210edeeccaf69294886"
source_revision = "323332d33f997de8394f24a193e1a76df720e01a"
source_repository = "kyutai/tts-voices"
source_path = "voice-donations/0a67.wav"
source_format = "wav"
license = "CC0-1.0"
dataset = "voice-donations"
variant = "original"
```

`source_format` is optional for compatibility with older persisted mappings. Do not replace the stable ref with `resolved.path`, persist cache locations, or use a derived WAV digest as the source pin.

Once resolved, VoiceRender passes `resolved.path` to the selected engine. For Pocket, call `PocketRuntime.prepare_voice(resolved.path)`; for Sopro, call `SoproRuntime.prepare_voice(resolved.path)`. PocketSynth owns Pocket-specific conditioning, while OnnxVoice remains responsible for Pocket ONNX bundle/runtime concerns.

## Catalog update model

The runtime catalog is packaged, deterministic, and does not scan Hugging Face or GitHub. Voicefolio maintainer workflows resolve upstream revisions, apply source-specific license and attribution rules, verify immutable-ref behavior, and produce release candidates. Matching refs and SHA-256 values preserve complete historical rows; changed bytes for an existing ID fail; removed upstream paths remain pinned; new paths receive new refs. Fine Read It demos are separately pinned linked assets and are not managed reference voices.

The older `migrate-pocket` command is historical/bootstrap compatibility tooling, not the active refresh path. Removing the Pocket prompt catalog and retiring OnnxVoice's transitional prompt APIs are separate migration phases.
