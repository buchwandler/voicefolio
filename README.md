# Voicefolio

Voicefolio is a small catalog and asset layer for **stable, previewable, integrity-pinned
reference voices**. It is intended to move reference-WAV ownership out of engine/model
bundle repositories such as `pocket-onnx-bundles` and make the same voice reference usable
by VoiceRender, RenderPlan, PocketSynth, SoproSynth, and future renderers.

The core rule is simple:

```text
stable ref + pinned source revision + SHA-256 -> exact WAV
```

Example stable reference:

```text
kyutai-tts-voices:voice-donations/0a67
```

Existing `kyutai-tts-voices:<id>` IDs are deliberately preserved so the catalog can move
without gratuitous identity churn.

## Install

## Install

```bash
python -m pip install voicefolio
voicefolio version
```

For native audio preview, install the optional playback dependencies with `python -m pip install 'voicefolio[playback]'`. Developers can install `python -m pip install -e '.[dev]'` or include playback as `python -m pip install -e '.[dev,playback]'`. Catalog, integration, and fetch consumers do not require NumPy, sounddevice, or soundfile.

Versioning is dynamic via `setuptools-scm`; there is no hard-coded package version and no `src/` directory.

## Commands

```bash
voicefolio list
voicefolio preview kyutai-tts-voices:voice-zero/peter_yearsley
voicefolio fetch kyutai-tts-voices:voice-zero/peter_yearsley
voicefolio export kyutai-tts-voices:voice-zero/peter_yearsley -o narrator.wav
```

The built-in Kyutai catalog contains the complete pinned 1,161-reference snapshot. Runtime commands use packaged catalog data and do not contact Hugging Face to discover voices.

- `preview` = verified download/cache + native playback; it waits until playback finishes and requires `voicefolio[playback]`.
- `fetch` = verified download/cache only; it does not play audio.
- `export` = exact pinned WAV + provenance sidecar.

`voicefolio preview --device DEVICE` selects an output device; numeric IDs are accepted. On Linux, native playback may also require the host PortAudio runtime. If playback dependencies are missing, Voicefolio reports: `Install voicefolio[playback] for native preview.` Catalog listing, validation, fetching, and export do not initialize the audio backend.

## Maintaining the authoritative Kyutai catalog

Voicefolio owns upstream discovery, license policy, and refreshes. Maintainers can build a candidate against the latest upstream commit while preserving the checked-in catalog as the immutable baseline:

```bash
voicefolio catalog build-kyutai \
  --repository kyutai/tts-voices \
  --revision main \
  --previous voicefolio/resources/catalogs/kyutai-tts-voices.json \
  --output /tmp/kyutai-tts-voices.json

voicefolio catalog verify /tmp/kyutai-tts-voices.json
```

When updating the packaged catalog, `build-kyutai` defaults both its output and previous baseline to the packaged catalog. Existing refs and rows are immutable: same bytes preserve the old row, a removed upstream path remains revision-pinned, changed bytes for an existing ID fail, and new paths are appended as new IDs. The scheduled Voicefolio workflow validates and deterministically rebuilds this catalog; normal runtime use remains packaged and network-independent. Validated catalog updates are distributed through Voicefolio releases; CI does not automatically publish to PyPI.

## Historical Pocket migration

`migrate-pocket` remains compatibility/bootstrap tooling for at least one release after `pocket-onnx-bundles` removes its prompt catalog. It is not the active catalog refresh path:

```bash
voicefolio migrate-pocket \
  ../pocket-onnx-bundles/catalog/voice-prompts.json \
  -o /tmp/kyutai-voicefolio.json

voicefolio catalog verify /tmp/kyutai-voicefolio.json
```

The command converts the historical Pocket `prompts` container to Voicefolio's schema-1 `voices` container without changing IDs or integrity pins.

## RenderPlan / VoiceRender contract

Voicefolio emits a portable managed reference rather than a local path:

```toml
renderer = "pocket"
target_id = "english_2026-04"

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

RenderPlan can already persist nested binding tables. VoiceRender should call `voicefolio.validate_voice_source()` during profile/preflight validation; it checks source pins without downloading the WAV. During execution, call `voicefolio.resolve_voice_source()` to revalidate the same pins and fetch the verified local asset. This keeps RenderProfiles portable and prevents machine-specific paths from becoming identity.
See `docs/voicerender-integration.md`.

## Catalog ownership

Voicefolio owns:

- direct upstream discovery and deterministic catalog refresh;
- stable source-qualified IDs;
- catalog metadata and provenance;
- source revision + SHA-256 integrity pins;
- the authoritative license policy and per-row metadata/evidence;
- caching, preview, and exact WAV export;
- renderer-neutral managed-reference resolution.

Voicefolio does **not** own TTS model bundles, embeddings, synthesis, text normalization, G2P,
render planning, or final audio mastering.

## License

Voicefolio source code is Apache-2.0. Catalog entries and downloaded WAVs keep their own licenses;
the package does not relicense them. A recording license alone should not be treated as a general
statement about biometric/voice-likeness rights in every jurisdiction or use case.
