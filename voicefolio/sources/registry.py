"""Maintainer-only dispatch for source-specific catalog verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..errors import CatalogError
from .fine_read_it_voices import verify_fine_read_it_catalog
from .kyutai_tts_voices import verify_kyutai_catalog
from .voice_zero import verify_voice_zero_catalog

Verifier = Callable[[Mapping[str, Any]], None]

_VERIFIERS: dict[str, Verifier] = {
    "fine-read-it-voices": verify_fine_read_it_catalog,
    "kyutai-tts-voices": verify_kyutai_catalog,
    "voice-zero": verify_voice_zero_catalog,
}


def verifier_for_namespace(namespace: str) -> Verifier:
    """Return the maintainer verifier registered for *namespace*."""
    try:
        return _VERIFIERS[namespace]
    except KeyError as exc:
        supported = ", ".join(sorted(_VERIFIERS))
        raise CatalogError(
            f"no maintained-source verifier registered for namespace {namespace!r}; "
            f"supported namespaces: {supported or '<none>'}"
        ) from exc


def verify_maintained_catalog(catalog: Mapping[str, Any]) -> None:
    """Verify a source catalog using its declared namespace."""
    namespace = catalog.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise CatalogError("catalog namespace must be a non-empty string")
    verifier_for_namespace(namespace)(catalog)
