from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .catalog import CATALOG_KIND, CATALOG_SCHEMA
from .models import CatalogError


def migrate_pocket_catalog(
    source: str | Path,
    destination: str | Path,
    *,
    namespace: str = "kyutai-tts-voices",
) -> Path:
    """Convert pocket-onnx-bundles voice-prompts.json without changing prompt IDs."""
    source_path = Path(source)
    destination_path = Path(destination)
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read Pocket catalog {source_path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise CatalogError("Pocket catalog root must be an object")
    prompts = raw.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise CatalogError("Pocket catalog must contain a non-empty prompts array")
    voices: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts):
        if not isinstance(prompt, Mapping):
            raise CatalogError(f"prompts[{index}] must be an object")
        row = dict(prompt)
        if "id" not in row or "sha256" not in row:
            raise CatalogError(f"prompts[{index}] is missing id/sha256")
        voices.append(row)
    output = {
        "schema": CATALOG_SCHEMA,
        "kind": CATALOG_KIND,
        "namespace": namespace,
        "source": raw.get("source", {}),
        "voices": voices,
    }
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination_path
