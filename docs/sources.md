# Maintained sources

Every packaged namespace has a source-specific builder and verifier. Runtime `Catalog.builtin()` loads all packaged catalog files in deterministic filename order; runtime use does not query Hugging Face or GitHub. Maintainer refresh workflows resolve one upstream revision, build candidates twice, verify immutable rows, and only then commit catalog changes.

| Namespace             | Upstream                      | Packaged reference data | Special handling                                                                              |
| --------------------- | ----------------------------- | ----------------------: | --------------------------------------------------------------------------------------------- |
| `kyutai-tts-voices`   | `kyutai/tts-voices`           |     1,161 released rows | Existing IDs and exact SHA-256 values are compatibility data.                                 |
| `fine-read-it-voices` | `zloezlo/fine-read-it-voices` |      228 reference WAVs | Each available synthesized demo is an independently pinned linked asset.                      |
| `voice-zero`          | `OwenTyme/voice-zero`         | 2,114 curated FLAC rows | Original and emotion variants use pinned source bytes; unresolved attribution is quarantined. |

The current Fine Read It catalog is pinned to commit `c78cad410088021052ccf044fb5eb8b464ecd66d`. The current Voice-Zero catalog is pinned to commit `490cfbee850a6d409076f477c766f567000a79b6`. Catalog rows retain their own source revision, repository, path, size, digest, license, and evidence; historical entry revisions can differ from the latest top-level discovery revision.

## Refresh commands

```bash
voicefolio catalog build-fine-read-it \
  --repository zloezlo/fine-read-it-voices \
  --revision main \
  --previous voicefolio/resources/catalogs/fine-read-it-voices.json \
  --output /tmp/fine-read-it.json

voicefolio catalog build-voice-zero \
  --repository OwenTyme/voice-zero \
  --revision main \
  --previous voicefolio/resources/catalogs/voice-zero.json \
  --output /tmp/voice-zero.json

voicefolio catalog verify /tmp/fine-read-it.json
voicefolio catalog verify /tmp/voice-zero.json
```

The Kyutai builder remains available as `voicefolio catalog build-kyutai`. A first Fine Read It or Voice-Zero build may use `--bootstrap` only when no previous catalog exists. An explicitly missing baseline fails closed; it must never silently disable append-only checks.

Fine Read It demos are not the reference WAV. Demo metadata is separate, and the browser requests one only through an explicit `asset=preview_demo` path. Voice-Zero emotion entries retain a `base_id` to their original reference. Accent is descriptive metadata and is not inferred into the language field.

See [license and provenance](license-and-provenance.md) before using catalog audio.
