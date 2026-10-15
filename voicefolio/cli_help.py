"""Adaptive narrow-terminal help formatting for the Voicefolio CLI."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import typer
from typer.core import TyperCommand, TyperGroup

NARROW_HELP_WIDTH = 72
_BaseHelpContext = TyperCommand.context_class
_BaseHelpFormatter = _BaseHelpContext.formatter_class


class AdaptiveHelpFormatter(_BaseHelpFormatter):  # type: ignore[valid-type,misc]
    """Use stacked definition lists when the available terminal is narrow."""

    def write_dl(
        self,
        rows: Sequence[tuple[str, str]],
        col_max: int = 30,
        col_spacing: int = 2,
    ) -> None:
        rows = [
            (term, description.replace(r"\[default:", "[default:"))
            for term, description in rows
        ]
        if self.width >= NARROW_HELP_WIDTH:
            super().write_dl(rows, col_max=col_max, col_spacing=col_spacing)
            return
        for index, (term, description) in enumerate(rows):
            self.write(f"{'':>{self.current_indent}}{term}\n")
            if description:
                with self.indentation(), self.indentation():
                    self.write_text(description)
            if index < len(rows) - 1:
                self.write("\n")


class AdaptiveHelpContext(_BaseHelpContext):  # type: ignore[valid-type,misc]
    formatter_class = AdaptiveHelpFormatter


class AdaptiveTyperCommand(TyperCommand):
    context_class = AdaptiveHelpContext


class AdaptiveTyperGroup(TyperGroup):
    context_class = AdaptiveHelpContext


class AdaptiveTyper(typer.Typer):
    """Typer app assigning the adaptive command class by default."""

    def command(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("cls", AdaptiveTyperCommand)
        return super().command(*args, **kwargs)
