from __future__ import annotations

try:
    from ._version import __version__
except ImportError:  # editable checkout before setuptools-scm generated the file
    try:
        from importlib.metadata import version

        __version__ = version("voicefolio")
    except Exception:
        __version__ = "0.0.dev0"

from .catalog import Catalog, load_catalog
from .integration import managed_reference, resolve_voice_source
from .models import ResolvedVoice, VoiceEntry, VoiceRef

__all__ = [
    "Catalog",
    "ResolvedVoice",
    "VoiceEntry",
    "VoiceRef",
    "__version__",
    "load_catalog",
    "managed_reference",
    "resolve_voice_source",
]
