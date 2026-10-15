# Usage

## Browse and filter

```bash
voicefolio list --namespace kyutai-tts-voices
voicefolio list --namespace fine-read-it-voices --pitch-band low --json
voicefolio list --namespace voice-zero --variant emotion
voicefolio show fine-read-it-voices:F002
voicefolio browse
voicefolio browse-web
```

`list` and the browser support namespace, dataset, language, license, variant, speaker, gender, pitch-band, and emotion filters. Search covers stable refs and selected descriptive metadata. Catalog results have a stable sort order.

The terminal browser controls are `/` for search, `l` for language, `s` for source namespace, `f` for speaker/gender/pitch-band/emotion, `n`/`p` for paging, a row number for preview, and `q` to quit. Filter changes reset paging; empty optional inputs clear a filter; invalid values preserve the previous value. Playback errors do not terminate the browser.

`browse-web` binds to `127.0.0.1` only. Its local API dynamically supplies source/facet counts, pages large catalogs, and inserts catalog text using text nodes. The page has a restrictive hash-based Content Security Policy and does not accept remote script/style resources.

## Fetch, preview, and export

```bash
voicefolio fetch kyutai-tts-voices:voice-donations/0a67
voicefolio preview kyutai-tts-voices:voice-donations/0a67
voicefolio export kyutai-tts-voices:voice-donations/0a67 -o narrator.wav
```

`fetch` downloads or verifies the exact pinned source bytes and prints the content-addressed cache path. WAV references retain the released cache layout; FLAC sources use a `.flac` suffix. `preview` plays the source WAV or FLAC and requires `voicefolio[playback]`.

`export` defaults to a renderer-ready WAV. For a FLAC source, deterministic conversion requires `voicefolio[audio]`; the derived WAV digest is distinct from the managed source SHA-256. To preserve exact FLAC bytes instead:

```bash
voicefolio export voice-zero:voices/example -o example.flac --format source
```

The example ref is illustrative; select an actual ref with `voicefolio list --namespace voice-zero`. Source exports require the matching `.wav` or `.flac` suffix unless `--force-extension` is explicitly provided. A provenance sidecar records source and output formats/digests.

Fine Read It synthesized demo recordings are separate linked assets, each independently size- and SHA-256-pinned. The web UI labels them `Synthesized demo`; they are not reference voices and are not returned from managed-reference resolution.

## Offline use and managed bindings

Packaged listing, `show`, binding generation, and catalog validation are offline. Use `--offline` for fetch, preview, export, or browser audio when only the verified cache may be used. Offline cache misses are reported rather than silently accessing the network.

```bash
voicefolio binding kyutai-tts-voices:voice-donations/0a67 --json
voicefolio validate
```

Bindings store the stable ref and source integrity/provenance pins, not cache paths. See [the VoiceRender integration contract](voicerender-integration.md).
