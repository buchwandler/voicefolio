# VoiceRender integration

Current VoiceRender already has the right conceptual distinction:

- machine-local `reference_audio` / `voice_source.kind = "reference"` is rejected in shared
  RenderProfiles because it is not portable;
- `managed_reference` is already understood by the Pocket adapter.

Voicefolio now ships the complete pinned Kyutai WAV catalog and offers synchronous native playback through `voicefolio preview`; `voicefolio fetch` remains download/cache only. This local CLI behavior does not change the portable `managed_reference` contract: its kind, resolver, stable value, integrity/provenance pins, license, dataset, and variant remain unchanged, with no machine-local path.
Voicefolio should become the generic resolver behind managed references instead of keeping the
Kyutai reference catalog inside Pocket/OnnxVoice asset ownership.

## Proposed integration boundary

Add Voicefolio as a small VoiceRender dependency or optional extra and resolve this shape:

```python
from voicefolio import resolve_voice_source

resolved = resolve_voice_source(
    request.options["voice_source"],
    offline=selection.offline,
)
# resolved.path is a verified local WAV
# resolved.entry contains stable ref + provenance
```

The RenderProfile stores no local path. It stores the stable ref, SHA-256, source revision,
repository, and source path. Voicefolio revalidates those pins before returning the local WAV.

For Pocket, VoiceRender can then call `PocketRuntime.prepare_voice(resolved.path)`. For Sopro it
can pass the same verified path to `SoproRuntime.prepare_voice()`. This makes the catalog
renderer-neutral.

## Suggested migration order

1. Publish Voicefolio with the complete migrated `kyutai-tts-voices` catalog.
2. Add Voicefolio resolution to VoiceRender for `resolver = "voicefolio"`.
3. Point Pocket managed-reference handling at Voicefolio rather than Pocket/OnnxVoice catalog code.
4. Add Sopro reference binding using the same managed-reference contract.
5. Remove `voice-prompts*.json` and prompt-specific schema ownership from `pocket-onnx-bundles`.
6. Remove obsolete Pocket-specific prompt catalog/cache code only after downstream releases require
   the Voicefolio-backed versions.

Do not change existing `kyutai-tts-voices:<id>` values during the migration.
