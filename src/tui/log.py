"""Scrolling result/log pane."""
from __future__ import annotations

from datetime import datetime

from textual.widgets import RichLog


class LogPane(RichLog):
    """One line per event, colored by outcome."""

    def __init__(self, **kwargs):
        super().__init__(highlight=False, markup=True, wrap=True, **kwargs)
        self.border_title = "Log"

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def info(self, msg: str) -> None:
        self.write(f"[dim]{self._ts()}[/dim] {msg}")

    def ok(self, who: str, msg: str) -> None:
        self.write(f"[dim]{self._ts()}[/dim] [green]OK[/green] {who}: {msg}")

    def fail(self, who: str, msg: str) -> None:
        self.write(f"[dim]{self._ts()}[/dim] [red]FAIL[/red] {who}: {msg}")

    def result(self, who: str, ok: bool, msg: str) -> None:
        (self.ok if ok else self.fail)(who, msg)
