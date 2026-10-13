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
voicefolio preview kyutai-tts-voices:voice-zero/peter_yearsley
voicefolio fetch kyutai-tts-voices:voice-zero/peter_yearsley
voicefolio export kyutai-tts-voices:voice-zero/peter_yearsley -o narrator.wav
```

The built-in Kyutai catalog includes the complete pinned 1,161-prompt snapshot. Command behavior:

- `preview` = verified download/cache + native playback; it waits until playback finishes.
- `fetch` = verified download/cache only; it does not play audio.
- `export` = exact pinned WAV + provenance sidecar.

`voicefolio preview --device DEVICE` selects an output device; numeric IDs are accepted. On Linux,
`sounddevice` requires PortAudio from the host system. Install your distribution's PortAudio runtime
package if preview reports that native playback is unavailable. Catalog listing, fetching, and export
do not initialize the audio backend.

## Maintaining older Pocket catalogs

The built-in catalog is complete; normal users do not need to run a migration. `migrate-pocket` remains
available to maintainers who need to convert a legacy Pocket prompt catalog while retaining its IDs
and integrity pins:

```bash
voicefolio migrate-pocket \
  ../pocket-onnx-bundles/catalog/voice-prompts.json \
  -o voicefolio/resources/catalogs/kyutai-tts-voices.json

voicefolio validate
```

The command converts the Pocket `prompts` container to Voicefolio's generic `voices` schema.

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
