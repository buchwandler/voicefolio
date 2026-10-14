# VoiceRender integration

Voicefolio provides the catalog and managed-reference resolver; VoiceRender retains render planning and engine dispatch. The persisted source remains portable and contains no machine-local cache path.

## Preflight and execution

Use metadata-only validation during profile loading or preflight. It applies the same catalog-pin checks as runtime resolution and does not download audio:

```python
from voicefolio import validate_voice_source

entry = validate_voice_source(request.options["voice_source"])
# entry contains stable ref, digest, source revision, and descriptive metadata.
```

At execution time, resolve and fetch the verified WAV:

```python
from voicefolio import resolve_voice_source

resolved = resolve_voice_source(
    request.options["voice_source"],
    offline=selection.offline,
    progress=on_voice_progress,  # optional FetchProgress callback
)
# resolved.path is a verified local WAV
# resolved.entry contains stable ref + provenance
```

`validate_voice_source()` requires `kind="managed_reference"`, `resolver="voicefolio"`, the catalog ref, SHA-256, source revision, repository, and path. If persisted, `license`, `dataset`, and `variant` must also match. Pin/description mismatches raise `IntegrityError`; a ref absent from the catalog raises `VoiceNotFoundError`. Preflight does not fetch or require a cache hit.

`resolve_voice_source()` calls the same validator before fetching, so preflight and execution cannot drift in their pin rules. Fetch exposes `OfflineError`, `DownloadError` (including `AccessError` and `AssetNotFoundError`), and `IntegrityError`; callers should branch on public exception types rather than parsing error strings. The optional `FetchProgress` callback reports `cache_check`, `download`, `verify`, and `ready` phases and can be adapted to VoiceRender's progress model.

Once resolved, VoiceRender passes `resolved.path` to the selected engine. For Pocket, call `PocketRuntime.prepare_voice(resolved.path)`; for Sopro, call `SoproRuntime.prepare_voice(resolved.path)`. PocketSynth owns Pocket-specific conditioning, while OnnxVoice remains responsible for Pocket ONNX bundle/runtime concerns.

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
license = "CC0-1.0"
dataset = "voice-donations"
variant = "original"
```

The stable ref plus integrity/provenance pins defines render identity. Do not replace it with `resolved.path`, persist cache locations, or change existing `kyutai-tts-voices:<id>` values.

## Catalog update model

The runtime catalog is packaged, deterministic, and does not scan Hugging Face. Voicefolio maintainer CI scans upstream, applies the Voicefolio-owned license policy, verifies the immutable-ID refresh rules, and produces catalog updates for Voicefolio releases. Existing rows retain their exact source revision and URL when their bytes match; missing upstream paths remain historical rows; changed bytes for an existing ID fail the refresh; new paths receive new refs.

The older `migrate-pocket` command is historical/bootstrap compatibility tooling, not the active refresh path. Removing the Pocket prompt catalog and retiring OnnxVoice's transitional prompt APIs are separate migration phases.
