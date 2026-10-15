# Architecture

```text
 Kyutai upstream        Fine Read It HF         Voice-Zero GitHub
        |                      |                        |
        +----------------------+------------------------+
                               |
                   source-specific maintainer builders
            pinned revisions + license/attribution evidence
                               |
                   append-only immutable-ref merge
                               |
                 packaged schema-1 catalog resources
           Kyutai             Fine Read It          Voice-Zero
                               |
                     deterministic wheel / sdist
                               |
       Catalog / preflight / verified source cache / CLI / browser
                               |
          +--------------------+---------------------+
          |                    |                     |
    exact WAV bytes      exact FLAC bytes      pinned demo assets
          |                    |
          |             optional deterministic
          |               FLAC-to-WAV recipe
          +--------------------+
                               |
                 renderer-ready WAV / export
                               |
              managed_reference + source SHA-256
                               |
                       VoiceRender clients
```

## Ownership and refresh

Voicefolio owns the source adapters, packaged snapshots, stable source-qualified IDs, metadata and per-row license evidence, integrity pins, cache/export behavior, and renderer-neutral managed-reference validation. Kyutai discovery uses Hugging Face, Fine Read It uses bounded Hugging Face dataset APIs and separately pinned demo assets, and Voice-Zero uses bounded GitHub tree/content APIs. Runtime catalog loading is offline and deterministic; refresh operations are maintainer-only and explicitly networked.

Each namespace has its own append-only identity boundary. A matching ref and SHA-256 preserves the complete previous row; a changed digest for an existing ref fails; removed upstream files remain pinned historical rows; new IDs are appended at one resolved upstream revision. Source-specific verification checks attribution and license evidence. Ambiguous Voice-Zero files remain in quarantine diagnostics rather than being guessed into the catalog. Accent stays separate from language.

The catalogs retain schema 1 (`kind = "voicefolio-catalog"`). `Catalog.builtin()` loads all packaged catalog JSON resources in stable filename order, then merges explicit local catalogs with duplicate-ref conflict checks. Runtime list/show/binding/validation does not contact upstream services.

## Source bytes, materialization, and browser

The managed-reference SHA-256 always identifies exact upstream source bytes. WAV cache paths preserve the released layout; FLAC sources use `.flac` cache paths. Default export and VoiceRender resolution produce renderer-ready WAVs; FLAC conversion is an optional, deterministic `voicefolio[audio]` operation with its own output digest and recipe metadata. Native preview can play WAV or FLAC through the optional playback extra.

Fine Read It synthesized demos are linked assets with their own pinned URL, size, format, and SHA-256. They are fetched only on explicit demo request and never substitute for the reference asset or managed reference.

The local browser binds only to `127.0.0.1`. Facet and language endpoints drive source-aware filtering and paging; text is rendered as text nodes. Audio responses report their real source MIME type (`audio/wav` or `audio/flac`), while renderer-WAV requests are explicit. The server sets `nosniff`, `no-store`, and a hash-based restrictive Content Security Policy.

## Managed references and runtime

A managed reference contains the stable ref, source SHA-256, pinned source revision/repository/path, and descriptive license/dataset/variant metadata. VoiceRender calls `validate_voice_source()` during profile/preflight checks; this validates catalog pins without fetching audio. At execution time `resolve_voice_source()` revalidates, fetches and verifies source bytes, then returns a WAV suitable for renderer consumption (materializing FLAC only when needed). Persisted profiles retain source identity, never a machine-local cache path or derived WAV digest.

`voicefolio preview REF` verifies or fetches the source and plays WAV/FLAC synchronously when installed with `voicefolio[playback]`. `fetch` resolves exact source bytes without playback. The core catalog/integration install does not require soundfile, sounddevice, or a native audio backend.

## Cache and trust boundaries

Source downloads require HTTPS (with bounded safe redirects), enforce the pinned size and SHA-256, and publish atomically only after verification. Linked demos use independent pins and bounded downloads. Offline misses, access failures, missing pinned assets, transport failures, and integrity mismatches have distinct public error types. Source inclusion does not grant universal permission to use or clone a person's voice; users must review both the recording license and applicable likeness/consent rights.
