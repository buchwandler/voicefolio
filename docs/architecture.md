# Architecture

```text
      kyutai/tts-voices upstream
                 |
                 v
    Voicefolio maintainer tooling + CI
    pinned discovery / license policy
    immutable published-ID merge
                 |
                 v
    packaged schema-1 Kyutai catalog
                 |
        Voicefolio release artifact
                 |
                 v
  Catalog / preflight validation / fetch
      |                         |
      +---- verified cache      +---- exact WAV export / preview
                 |
                 v
        managed_reference
                 |
                 v
            VoiceRender
              /      \
             v        v
      PocketSynth   SoproSynth ...
                 |
                 v
          RenderPlan output
```

## Ownership and refresh

Voicefolio is the authoritative owner of Kyutai reference IDs, catalog metadata, license policy and evidence, integrity pins, download/cache/offline behavior, and engine-neutral managed-reference validation. Kyutai-specific upstream discovery lives in maintainer tooling rather than the generic `Catalog` model. Normal `list`, `fetch`, preflight, and resolution use the packaged catalog and never discover against upstream `main`.

The packaged catalog keeps schema 1 (`kind = "voicefolio-catalog"`) and the `kyutai-tts-voices` namespace. Refresh is append-only by public identity:

- same ID and same SHA-256: preserve the entire published row, including its source revision, URL, and license evidence;
- existing ID absent upstream: preserve its revision-pinned historical row;
- existing ID with a different SHA-256: fail the refresh; never reassign the ref;
- new ID: append a row pinned to the newly resolved 40-character source commit.

Therefore, historical entry revisions may differ from the latest discovery revision recorded in top-level `source` metadata. CI verifies the baseline, rebuilds twice for byte-identical output, and commits only a verified catalog update. Catalog updates are included in Voicefolio releases; the scheduled workflow does not publish to PyPI.

## Managed references and runtime

A stable reference identifies one exact WAV through its SHA-256 and pinned source revision. VoiceRender calls `validate_voice_source()` during profile/preflight checks; it validates required pins and optional descriptive fields without downloading. At execution time `resolve_voice_source()` applies the same validation and fetches/verifies the exact WAV before returning a local path. Persisted RenderProfiles retain the managed ref and provenance, never a machine-local cache path.

`voicefolio preview REF` verifies or fetches the content-addressed asset and plays it synchronously when installed with `voicefolio[playback]`. `fetch` resolves the same verified asset without playback. The core catalog/integration install does not require NumPy or native audio packages.

## Cache rule

Cache paths are content-addressed by SHA-256. Paths are intentionally not part of render identity. All fetched assets are verified before atomic publication to the cache; offline misses, access failures, missing pinned upstream assets, transport failures, and integrity mismatches have distinct public error types.
