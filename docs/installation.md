# Installation

The core package supports catalog listing, validation, pinned downloads, managed references, and WAV source export without installing an audio backend:

```bash
python -m pip install voicefolio
voicefolio --version
```

Optional features:

- `voicefolio[playback]` installs `soundfile` and `sounddevice` for native WAV/FLAC preview.
- `voicefolio[audio]` installs `soundfile` for deterministic conversion of pinned FLAC sources to renderer WAVs.
- `voicefolio[cli]` installs Rich terminal support; basic help and progress output remain usable without it.

On Linux, native playback may also need the host PortAudio library. The core import and runtime catalog operations do not initialize `sounddevice` or `soundfile`.

For development and documentation checks:

```bash
python -m pip install -e '.[dev]'
python -m pip install -r docs/requirements.txt
```

Voicefolio does not install audio files as part of the package. The catalogs contain source metadata and integrity pins; audio is fetched and verified only when requested.
