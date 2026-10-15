"""Shared invariants for deterministic maintained-source catalog builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from ..errors import CatalogError


def merge_immutable_rows(
    previous_rows: Sequence[Mapping[str, Any]],
    discovered_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge source rows append-only, retaining old metadata for unchanged bytes."""
    previous: dict[str, dict[str, Any]] = {}
    for row in previous_rows:
        voice_id = row.get("id")
        if not isinstance(voice_id, str) or not voice_id:
            raise CatalogError("previous source row has no valid id")
        if voice_id in previous:
            raise CatalogError(f"previous source catalog contains duplicate id {voice_id!r}")
        previous[voice_id] = deepcopy(dict(row))

    discovered: dict[str, dict[str, Any]] = {}
    for row in discovered_rows:
        voice_id = row.get("id")
        if not isinstance(voice_id, str) or not voice_id:
            raise CatalogError("discovered source row has no valid id")
        if voice_id in discovered:
            raise CatalogError(f"discovery returned duplicate id {voice_id!r}")
        discovered[voice_id] = deepcopy(dict(row))

    merged = deepcopy(previous)
    for voice_id, current in discovered.items():
        old = previous.get(voice_id)
        if old is None:
            merged[voice_id] = current
            continue
        if old.get("sha256") != current.get("sha256"):
            raise CatalogError(
                f"immutable-ref collision for {voice_id!r}: source SHA-256 changed "
                f"from {old.get('sha256')!r} to {current.get('sha256')!r}"
            )
        # SHA equality freezes the complete published row, including provenance/metadata.

    return [merged[voice_id] for voice_id in sorted(merged)]
