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

```bash
python -m pip install -e '.[dev]'
voicefolio version
```

Versioning is dynamic via `setuptools-scm`; there is no hard-coded package version and no
`src/` directory.

## MVP commands

```bash
voicefolio list
voicefolio list --dataset voice-donations --license CC0-1.0
voicefolio show kyutai-tts-voices:voice-donations/0a67
voicefolio preview kyutai-tts-voices:voice-donations/0a67
voicefolio browse
voicefolio export kyutai-tts-voices:voice-donations/0a67 -o narrator.wav
voicefolio binding kyutai-tts-voices:voice-donations/0a67 \
  --renderer pocket --target-id english_2026-04
```

`preview` and the browser UI download through Voicefolio, verify size + SHA-256, and serve/open
the cached WAV. `export` writes both the WAV and a `.voicefolio.json` provenance sidecar.

## Moving the current Pocket catalog

The bundled MVP catalog intentionally contains only a small representative subset of the
current 1,161-entry Pocket prompt catalog so the source ZIP stays compact. Convert the complete
existing catalog without changing prompt IDs:

```bash
voicefolio migrate-pocket \
  ../pocket-onnx-bundles/catalog/voice-prompts.json \
  -o voicefolio/resources/catalogs/kyutai-tts-voices.json

voicefolio validate
```

After review, remove the old prompt catalog from `pocket-onnx-bundles` and make Voicefolio the
owner. The migration copies the existing records and changes only the container schema from
Pocket-specific `prompts` to generic Voicefolio `voices`.

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

RenderPlan can already persist nested binding tables. VoiceRender should resolve the source with
`voicefolio.resolve_voice_source()` before handing the verified local WAV to a renderer. That
keeps RenderProfiles portable and prevents machine-specific paths from becoming identity.
See `docs/voicerender-integration.md`.

## Catalog ownership

Voicefolio owns:

- stable source-qualified IDs;
- catalog metadata and provenance;
- source revision + SHA-256 integrity pins;
- license metadata/evidence;
- caching, preview, and exact WAV export;
- renderer-neutral managed-reference resolution.

Voicefolio does **not** own TTS model bundles, embeddings, synthesis, text normalization, G2P,
render planning, or final audio mastering.

## License

Voicefolio source code is Apache-2.0. Catalog entries and downloaded WAVs keep their own licenses;
the package does not relicense them. A recording license alone should not be treated as a general
statement about biometric/voice-likeness rights in every jurisdiction or use case.
