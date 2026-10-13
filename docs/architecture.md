# Architecture

```text
upstream voice archives
        |
        v
  Voicefolio catalog
  stable ref / license
  revision / sha256
        |
        +---- native local preview (sounddevice)
        +---- exact WAV export
        +---- verified local cache
        |
        v
managed_reference
        |
        v
    VoiceRender
       /   \
      v     v
 PocketSynth SoproSynth ...
        |
        v
    RenderPlan output
```

The catalog is independent of a synthesis engine. A stable reference identifies one exact source
WAV through its SHA-256 and source revision. Engine-specific prepared voice states or embeddings
are derived artifacts and must not replace the catalog identity.

`voicefolio preview REF` verifies or fetches the content-addressed cache asset and plays the exact WAV synchronously through sounddevice. `fetch` resolves the same verified asset without playback.

## ID rule

A public Voicefolio reference is `<namespace>:<id>`, for example
`kyutai-tts-voices:vctk/p225_023`. Published refs must never be reassigned to different audio.
If a different sample is needed, publish a different ID. Enhanced samples remain separate IDs,
matching the existing Pocket catalog.

## Cache rule

Cache paths are content-addressed by SHA-256. Paths are intentionally not part of render identity.
All fetches are verified before atomic publication to the cache.
