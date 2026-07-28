"""Modal to pick an operation, value, and target scope."""
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Select

from ..ops import OP_SPECS, OpKind


@dataclass
class EditRequest:
    kind: OpKind
    value: str
    scope: str  # "selected" | "all" | "current"
    source: str = "tui"  # custom status only: "tui" (typed) | "discord" (pull current)


class EditScreen(ModalScreen[EditRequest | None]):
    """Returns an EditRequest on Run, or None on Cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    EditScreen { align: center middle; }
    #box {
        grid-size: 1;
        grid-rows: auto auto auto auto auto auto auto auto;
        padding: 1 2;
        width: 66;
        height: auto;
        border: thick $accent;
        background: $surface;
    }
    #box Label { margin-top: 1; }
    #hint { color: $text-muted; }
    #buttons { height: auto; align: right middle; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """

    def compose(self) -> ComposeResult:
        with Grid(id="box"):
            yield Label("Operation")
            yield Select(
                [(spec.label, spec.kind) for spec in OP_SPECS],
                prompt="Choose an operation",
                id="op",
                allow_blank=False,
            )
            yield Label("Value", id="value-label")
            yield Input(placeholder="…", id="value")
            yield Label("", id="hint")
            yield Label("Custom status source")
            with RadioSet(id="source"):
                yield RadioButton("Type value", value=True, id="source-tui")
                yield RadioButton("Pull current from Discord", id="source-discord")
            with RadioSet(id="scope"):
                yield RadioButton("Selected accounts", value=True, id="scope-selected")
                yield RadioButton("All accounts", id="scope-all")
                yield RadioButton("Current row", id="scope-current")
            with Horizontal(id="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Run", variant="primary", id="run")

    def on_mount(self) -> None:
        self._sync_hint()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._sync_hint()

    def _sync_hint(self) -> None:
        select = self.query_one("#op", Select)
        kind = select.value
        spec = next((s for s in OP_SPECS if s.kind == kind), None)
        hint = self.query_one("#hint", Label)
        value_input = self.query_one("#value", Input)
        if spec is None:
            hint.update("")
            return
        hint.update(f"Expected: {spec.value_hint}")
        value_input.placeholder = spec.value_hint

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        kind = self.query_one("#op", Select).value
        value = self.query_one("#value", Input).value
        scope = self._scope()
        if kind is Select.BLANK or kind is None:
            self.app.bell()
            return
        self.dismiss(EditRequest(kind=kind, value=value, scope=scope, source=self._source()))

    def _scope(self) -> str:
        pressed = self.query_one("#scope", RadioSet).pressed_button
        if pressed is None:
            return "selected"
        return {"scope-selected": "selected", "scope-all": "all", "scope-current": "current"}[
            pressed.id
        ]

    def _source(self) -> str:
        pressed = self.query_one("#source", RadioSet).pressed_button
        if pressed is None:
            return "tui"
        return {"source-tui": "tui", "source-discord": "discord"}[pressed.id]
