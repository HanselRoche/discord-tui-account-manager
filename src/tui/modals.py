"""Small input modals: passphrase, add-token, confirm."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class PassphraseScreen(ModalScreen[str | None]):
    """Prompt for the vault passphrase. Returns the string or None on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    CSS = """
    PassphraseScreen { align: center middle; }
    #box { padding: 1 2; width: 56; height: auto; border: thick $accent; background: $surface; }
    #box Label { margin-bottom: 1; }
    #buttons { height: auto; align: right middle; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """

    def __init__(self, new_vault: bool):
        super().__init__()
        self._new = new_vault

    def compose(self) -> ComposeResult:
        with Grid(id="box"):
            msg = "Create a passphrase for the new vault:" if self._new else "Vault passphrase:"
            yield Label(msg)
            yield Input(password=True, id="pass", placeholder="passphrase")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Unlock", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#pass", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._submit()

    def _submit(self) -> None:
        value = self.query_one("#pass", Input).value
        if value:
            self.dismiss(value)
        else:
            self.app.bell()


class AddTokenScreen(ModalScreen[tuple[str, str] | None]):
    """Collect a label + token. Returns (label, token) or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    CSS = """
    AddTokenScreen { align: center middle; }
    #box { padding: 1 2; width: 64; height: auto; border: thick $accent; background: $surface; }
    #box Label { margin-top: 1; }
    #buttons { height: auto; align: right middle; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """

    def compose(self) -> ComposeResult:
        with Grid(id="box"):
            yield Label("Label (nickname for this account)")
            yield Input(id="label", placeholder="e.g. alt-1")
            yield Label("User token")
            yield Input(id="token", password=True, placeholder="token")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Add", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#label", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        label = self.query_one("#label", Input).value.strip()
        token = self.query_one("#token", Input).value.strip()
        if not label or not token:
            self.app.bell()
            return
        self.dismiss((label, token))


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No confirmation."""

    BINDINGS = [("escape", "no", "No")]
    CSS = """
    ConfirmScreen { align: center middle; }
    #box { padding: 1 2; width: 56; height: auto; border: thick $error; background: $surface; }
    #buttons { height: auto; align: right middle; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """

    def __init__(self, question: str):
        super().__init__()
        self._q = question

    def compose(self) -> ComposeResult:
        with Grid(id="box"):
            yield Label(self._q)
            with Horizontal(id="buttons"):
                yield Button("No", id="no")
                yield Button("Yes", variant="error", id="yes")

    def action_no(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")
