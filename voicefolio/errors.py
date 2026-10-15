"""Canonical public exception hierarchy for Voicefolio."""

from __future__ import annotations


class VoicefolioError(Exception):
    """Base error for public Voicefolio failures."""


class CatalogError(VoicefolioError):
    """Catalog data is malformed or inconsistent."""


class VoiceNotFoundError(VoicefolioError):
    """A stable voice reference is not present in the active catalog."""


class IntegrityError(VoicefolioError):
    """Downloaded, cached, or exported data does not match its integrity pin."""


class OfflineError(VoicefolioError):
    """A requested asset is unavailable because offline mode is enabled."""


class DownloadError(VoicefolioError):
    """A cataloged asset could not be downloaded."""


class AccessError(DownloadError):
    """The upstream provider denied access to a cataloged asset."""


class AssetNotFoundError(DownloadError):
    """A cataloged asset is missing at its pinned upstream revision."""


class PlaybackError(VoicefolioError):
    """A verified local audio asset could not be played."""


class MissingAudioDependencyError(PlaybackError):
    """An optional audio dependency required for playback/materialization is absent."""


class MaterializationError(VoicefolioError):
    """A source asset could not be converted into a renderer-ready artifact."""
