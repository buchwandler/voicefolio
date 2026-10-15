from __future__ import annotations

import json

import pytest

from voicefolio.errors import CatalogError, MaterializationError, MissingAudioDependencyError
from voicefolio.models import CatalogError as ModelCatalogError
from voicefolio.progress import ProgressEvent, emit_progress


def test_progress_event_details_are_json_safe_immutable_and_detached():
    original = {"nested": {"values": [1, "two"]}}
    event = ProgressEvent("catalog.hash", "update", 1, 2, details=original)
    original["nested"]["values"].append(3)
    assert event.to_dict()["details"] == {"nested": {"values": [1, "two"]}}
    assert json.loads(json.dumps(event.to_dict()))["phase"] == "catalog.hash"
    with pytest.raises(TypeError):
        event.details["new"] = "value"  # type: ignore[index]


@pytest.mark.parametrize(
    "details",
    [{1: "non-string key"}, {"not-json": object()}, {"not-finite": float("nan")}],
)
def test_progress_event_rejects_non_json_details(details):
    with pytest.raises((TypeError, ValueError)):
        ProgressEvent("download", "update", details=details)


def test_progress_callbacks_propagate_observer_errors():
    def fail(_event):
        raise RuntimeError("observer failed")

    with pytest.raises(RuntimeError, match="observer failed"):
        emit_progress(fail, ProgressEvent("download", "started"))


def test_models_reexports_canonical_errors_and_new_error_types_exist():
    assert ModelCatalogError is CatalogError
    assert issubclass(MissingAudioDependencyError, Exception)
    assert issubclass(MaterializationError, Exception)
