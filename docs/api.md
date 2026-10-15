# Python API and error handling

The package exposes the catalog, stable-reference models, source resolution, validation, progress events, and public errors; exact-byte fetching is available from `voicefolio.cache`. Importing `voicefolio` does not import or initialize `sounddevice`, `soundfile`, a browser, or network clients.

```python
from voicefolio import Catalog, resolve_voice_source, validate_voice_source
from voicefolio.cache import fetch

catalog = Catalog.builtin()
entry = catalog.get("kyutai-tts-voices:voice-donations/0a67")
resolved = fetch(entry, offline=True)  # exact source bytes
```

For managed references, `validate_voice_source(mapping)` checks the catalog ref and source pins without downloading. `resolve_voice_source(mapping, offline=..., progress=...)` applies the same validation, fetches/verifies the source, and returns a renderer-ready WAV. FLAC materialization is lazy and requires `voicefolio[audio]`. The lower-level `voicefolio.cache.fetch(entry, ...)` and CLI `fetch` command return the original WAV or FLAC source bytes.

## Progress

Progress is delivered as immutable, JSON-safe `ProgressEvent` values. A callback receives one event at a time; callbacks should not be allowed to corrupt verified cache state. Structured command output remains free of progress text. Terminal progress is emitted only when appropriate for the terminal and output mode.

## Errors

Catch public `VoicefolioError` subclasses rather than parsing messages. They distinguish catalog/validation failures, missing refs/assets, access and transport failures, offline cache misses, integrity failures, playback failures, missing optional audio dependencies, and materialization errors. CLI boundaries render a concise actionable error and return a non-zero status.

See [the VoiceRender integration contract](voicerender-integration.md) for persisted binding fields and preflight/execution sequencing.
