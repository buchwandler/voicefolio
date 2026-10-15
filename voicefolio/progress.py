"""Provider-neutral progress events for longer Voicefolio workflows."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeAlias

JSONValue: TypeAlias = str | int | float | bool | None | list[Any] | dict[str, Any]
ProgressCallback: TypeAlias = Callable[["ProgressEvent"], None]


def _freeze_json(value: Any, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must contain only finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError(f"{field_name} object keys must be strings")
        return MappingProxyType(
            {key: _freeze_json(item, field_name) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field_name) for item in value)
    raise TypeError(f"{field_name} must contain only JSON-safe values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Immutable progress event with JSON-safe, detached details."""

    phase: str
    kind: str
    completed: int | None = None
    total: int | None = None
    message: str | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("progress phase must be a non-empty string")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("progress kind must be a non-empty string")
        for name, value in (("completed", self.completed), ("total", self.total)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"progress {name} must be a non-negative integer or None")
        if (
            self.completed is not None
            and self.total is not None
            and self.completed > self.total
        ):
            raise ValueError("progress completed cannot exceed total")
        if not isinstance(self.details, Mapping):
            raise TypeError("progress details must be a mapping")
        object.__setattr__(self, "details", _freeze_json(self.details, "progress details"))

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-serializable event mapping."""
        return {
            "phase": self.phase,
            "kind": self.kind,
            "completed": self.completed,
            "total": self.total,
            "message": self.message,
            "details": _thaw_json(self.details),
        }


def emit_progress(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    """Notify a consumer synchronously; callback exceptions intentionally propagate."""
    if callback is not None:
        callback(event)
