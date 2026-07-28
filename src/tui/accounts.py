"""Accounts DataTable with multi-select."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import DataTable

from ..models import Account, ConnState

_STATE_STYLE = {
    ConnState.ONLINE: ("● online", "green"),
    ConnState.CONNECTING: ("◌ connecting", "yellow"),
    ConnState.OFFLINE: ("○ offline", "grey50"),
    ConnState.DEAD: ("✗ dead token", "red"),
}

# Colour for the Discord status dot (distinct from the gateway ConnState above).
_STATUS_STYLE = {
    "online": "green",
    "idle": "yellow",
    "dnd": "red",
    "invisible": "grey50",
    "offline": "grey50",
}


class AccountsTable(DataTable):
    """Rows map 1:1 to `Account` objects held by the app.

    Selection is stored on the `Account.selected` flag so batch ops can read it
    without the table. `space` toggles the cursor row; `a`/`n` select all/none.
    """

    def __init__(self, accounts: list[Account], **kwargs):
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.accounts = accounts
        self.border_title = "Accounts"

    def on_mount(self) -> None:
        self.add_column("sel", width=3)
        self.add_column("label", width=16)
        self.add_column("username", width=22)
        self.add_column("state", width=16)
        self.add_column("status", width=24)
        self.add_column("last result")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        """Rebuild the table from the current account list + state."""
        self.clear()
        for acc in self.accounts:
            self.add_row(*self._row_cells(acc), key=acc.label)

    def _row_cells(self, acc: Account):
        sel = Text("[x]" if acc.selected else "[ ]", style="cyan" if acc.selected else "")
        state_text, style = _STATE_STYLE.get(acc.conn_state, ("?", ""))
        status_style = _STATUS_STYLE.get(acc.status or "", "grey58")
        return (
            sel,
            Text(acc.label),
            Text(acc.username or "—"),
            Text(state_text, style=style),
            Text(acc.status_display, style=status_style),
            Text(acc.last_result or "", style="grey58"),
        )

    def _update_row(self, acc: Account) -> None:
        try:
            self.update_cell(acc.label, "sel", self._row_cells(acc)[0])
        except Exception:
            self.refresh_rows()

    # ---- selection -------------------------------------------------------

    @property
    def cursor_account(self) -> Account | None:
        if not self.accounts or self.cursor_row is None:
            return None
        if 0 <= self.cursor_row < len(self.accounts):
            return self.accounts[self.cursor_row]
        return None

    def toggle_cursor(self) -> None:
        acc = self.cursor_account
        if acc is not None:
            acc.selected = not acc.selected
            self.refresh_rows()

    def select_all(self, value: bool) -> None:
        for acc in self.accounts:
            acc.selected = value
        self.refresh_rows()

    def selected_accounts(self) -> list[Account]:
        chosen = [a for a in self.accounts if a.selected]
        if chosen:
            return chosen
        acc = self.cursor_account
        return [acc] if acc is not None else []
