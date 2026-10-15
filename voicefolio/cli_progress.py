"""TTY-aware progress rendering kept out of Voicefolio's public import path."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from .models import FetchProgress
from .progress import ProgressEvent


class CliProgress:
    """Render progress to stderr, using Rich only for capable, colored TTYs."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.use_rich = (
            self.is_tty
            and "NO_COLOR" not in os.environ
            and os.environ.get("TERM", "").lower() != "dumb"
        )
        self._console: Any | None = None
        self._progress: Any | None = None
        self._tasks: dict[str, Any] = {}

    def __enter__(self) -> CliProgress:  # noqa: PYI034
        if self.use_rich:
            try:
                from rich.console import Console
                from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
            except ImportError:
                self.use_rich = False
            else:
                self._console = Console(file=self.stream, stderr=True, force_terminal=True)
                self._progress = Progress(
                    SpinnerColumn(),
                    TextColumn("{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed}/{task.total}"),
                    console=self._console,
                    transient=True,
                )
                self._progress.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._progress is not None:
            self._progress.stop()

    def __call__(self, event: ProgressEvent | FetchProgress) -> None:
        phase: str
        if isinstance(event, FetchProgress):
            phase = event.phase
            completed = event.completed
            total = event.total
            message = event.ref
        else:
            phase = event.phase
            completed = event.completed
            total = event.total
            message = event.message or event.kind
        label = f"{phase.replace('.', ' ').replace('_', ' ')}: {message}"
        if self._progress is not None:
            task = self._tasks.get(phase)
            if task is None:
                task = self._progress.add_task(label, total=total)
                self._tasks[phase] = task
            self._progress.update(
                task,
                description=label,
                total=total,
                completed=completed if completed is not None else 0,
            )
            return
        details = ""
        if completed is not None:
            details = f" ({completed}/{total if total is not None else '?'})"
        print(f"{label}{details}", file=self.stream, flush=True)


def progress_callback(stream: TextIO | None = None) -> tuple[CliProgress, Callable[..., None]]:
    """Return a context manager and callback for progress-aware CLI commands."""
    renderer = CliProgress(stream)
    return renderer, renderer
