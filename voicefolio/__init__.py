from __future__ import annotations

try:
    from ._version import __version__
except ImportError:  # editable checkout before setuptools-scm generated the file
    try:
        from importlib.metadata import version

        __version__ = version("voicefolio")
    except ImportError:
        __version__ = "0.0.dev0"

from .catalog import Catalog, load_catalog
from .errors import MaterializationError, MissingAudioDependencyError
from .integration import managed_reference, resolve_voice_source, validate_voice_source
from .models import (
    AccessError,
    AssetNotFoundError,
    CatalogError,
    DownloadError,
    FetchProgress,
    IntegrityError,
    MaterializedVoice,
    OfflineError,
    PlaybackError,
    ResolvedVoice,
    VoiceEntry,
    VoicefolioError,
    VoiceNotFoundError,
    VoiceRef,
)
from .progress import ProgressCallback, ProgressEvent

__all__ = [
    "AccessError",
    "AssetNotFoundError",
    "Catalog",
    "CatalogError",
    "DownloadError",
    "FetchProgress",
    "IntegrityError",
    "MaterializationError",
    "MaterializedVoice",
    "MissingAudioDependencyError",
    "OfflineError",
    "PlaybackError",
    "ProgressCallback",
    "ProgressEvent",
    "ResolvedVoice",
    "VoiceEntry",
    "VoiceNotFoundError",
    "VoiceRef",
    "VoicefolioError",
    "__version__",
    "load_catalog",
    "managed_reference",
    "resolve_voice_source",
    "validate_voice_source",
]
