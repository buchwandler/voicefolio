# Voicefolio

Voicefolio is a small catalog and asset layer for **stable, previewable, integrity-pinned
reference voices**. It is intended to move reference-WAV ownership out of engine/model
bundle repositories such as `pocket-onnx-bundles` and make the same voice reference usable
by VoiceRender, RenderPlan, PocketSynth, SoproSynth, and future renderers.

The core rule is simple:

```text
stable ref + pinned source revision + SHA-256 -> exact source bytes; renderer WAV when needed
```

Example stable reference:

```text
kyutai-tts-voices:voice-donations/0a67
```

Existing `kyutai-tts-voices:<id>` IDs are deliberately preserved so the catalog can move
without gratuitous identity churn.

## Install

```bash
python -m pip install voicefolio
voicefolio version
```

For native playback, install `voicefolio[playback]`; for converting pinned FLAC sources into renderer WAVs, install `voicefolio[audio]`. The core install keeps both optional audio stacks lazy. Developers can install `python -m pip install -e '.[dev]'`.

Versioning is dynamic via `setuptools-scm`; there is no hard-coded package version and no `src/` directory.

## Commands

```bash
voicefolio list --namespace kyutai-tts-voices
voicefolio list --namespace fine-read-it-voices --pitch-band low
voicefolio list --namespace voice-zero --variant emotion
voicefolio browse
voicefolio browse-web
voicefolio preview kyutai-tts-voices:voice-zero/peter_yearsley
voicefolio fetch kyutai-tts-voices:voice-zero/peter_yearsley
voicefolio export kyutai-tts-voices:voice-zero/peter_yearsley -o narrator.wav
```

`browse` is a small terminal loop: `/` searches; `l` changes the language; `s` filters by source namespace; and `f` selects speaker, gender, pitch band, or emotion. `n`/`p` pages through stable, sorted results, a row number previews, and `q` quits. Empty optional filters clear them; invalid filter values leave the active filter unchanged and playback errors do not end the browser.

- `browse-web` opens the local browser addon on `127.0.0.1`; it discovers namespaces/facets dynamically, pages catalog results, and previews pinned WAV/FLAC references plus separately labeled synthesized demos. FLAC-to-WAV browser playback is requested explicitly and uses the optional `audio` extra.

Language describes the language of a reference recording where authoritative source evidence exists. `und` means the language is not authoritatively known; language is not an accent label. Filtering is descriptive only and never changes stable refs, source revisions, or SHA-256 integrity pins.

Terminal browse controls:

```text
/ search
l language
s source/namespace
f facets
n next
p previous
<number> preview
q quit
```

Each release ships pinned Kyutai, Fine Read It, and Voice-Zero catalog snapshots. The released Kyutai baseline retains all 1,161 immutable references; new source namespaces append independently. Runtime list/show/binding/validation use packaged catalogs and do not perform upstream discovery.

- `preview` = verified source fetch/cache + native WAV/FLAC playback; it waits until playback finishes and requires `voicefolio[playback]`.
- `fetch` = verified source download/cache only; it does not play audio and prints a format-correct `.wav` or `.flac` path.
- `export` defaults to a renderer-ready WAV; FLAC conversion requires `voicefolio[audio]`. Use `--format source` to preserve exact source bytes and a matching source extension.
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

## Maintaining the Fine Read It catalog

Fine Read It is maintained as a separate source namespace. Build a review candidate from an upstream revision, keeping the packaged catalog as the immutable baseline:

```bash
voicefolio catalog build-fine-read-it \
  --repository zloezlo/fine-read-it-voices \
  --revision main \
  --output /tmp/fine-read-it-voices.json

voicefolio catalog verify /tmp/fine-read-it-voices.json
```

The first build requires an explicit `--bootstrap` only when no previous catalog exists. Normal refreshes default to the packaged Fine Read It catalog; they preserve existing rows and fail if an existing stable ID changes audio bytes. The current packaged snapshot contains 228 reference voices, with each available synthesized preview demo pinned as a separate linked asset. Runtime catalog and cache access do not discover upstream data; linked demos are fetched only on request and verified by their own size and SHA-256 pins. Preserve each source row's revision, path, attribution, and license evidence when reviewing updates.

## Maintaining the Voice-Zero catalog

Voice-Zero has its own pinned, append-only namespace and refresh workflow:

```bash
voicefolio catalog build-voice-zero \
  --repository OwenTyme/voice-zero \
  --revision main \
  --previous voicefolio/resources/catalogs/voice-zero.json \
  --output /tmp/voice-zero.json
voicefolio catalog verify /tmp/voice-zero.json
```

The packaged snapshot contains 2,114 curated FLAC references (original and emotion variants). File-level attribution is resolved conservatively against the pinned upstream evidence; 42 unresolved assets are retained as quarantine diagnostics rather than assigned guessed attribution. Accent is descriptive metadata, not a language label. Review each row's license and attribution before use.

## Source bytes, WAV rendering, and demos

`fetch` and managed-reference SHA-256 pins identify exact upstream source bytes. WAV sources keep the historical cache path; FLAC sources cache as `.flac`. `export` defaults to a renderer-ready WAV (install `voicefolio[audio]` for FLAC conversion), while `--format source` preserves exact FLAC bytes and requires a matching `.flac` output suffix unless `--force-extension` is used. Derived WAVs have independent digests and do not replace the managed source pin. Fine Read It synthesized demos are separate pinned linked assets; the browser labels their control `Synthesized demo`, and they are never returned as a reference voice.

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

RenderPlan can already persist nested binding tables. VoiceRender should call `voicefolio.validate_voice_source()` during profile/preflight validation; it checks the pinned source identity without downloading audio. During execution, `voicefolio.resolve_voice_source()` revalidates the same pins, fetches and verifies exact source bytes, and returns a renderer-ready WAV (materializing FLAC only when needed). The managed reference always retains the source digest, not the derived WAV digest.
See `docs/voicerender-integration.md`.

## Catalog ownership

Voicefolio owns:

- direct upstream discovery and deterministic catalog refresh;
- stable source-qualified IDs;
- catalog metadata and provenance;
- source revision + SHA-256 integrity pins;
- the authoritative license policy and per-row metadata/evidence;
- source-byte caching, renderer WAV materialization, and preview/export;
- renderer-neutral managed-reference resolution.

Voicefolio does **not** own TTS model bundles, embeddings, synthesis, text normalization, G2P,
render planning, or final audio mastering.

## License

Voicefolio source code is Apache-2.0. Catalog entries and downloaded source assets keep their own licenses; the package does not relicense them. Catalog rows may contain mixed terms, including non-commercial restrictions and `NOASSERTION` where evidence remains inconclusive. Inspect each entry's license and attribution before use:

```bash
voicefolio list --license CC0-1.0
voicefolio show kyutai-tts-voices:voice-donations/0a67
```

A recording license alone should not be treated as a general statement about biometric or
voice-likeness rights in every jurisdiction or use case.
