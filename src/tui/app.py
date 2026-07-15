"""Textual app tying vault, accounts table, presence manager, and ops together."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header

from .. import presence_config, vault
from ..batch import run_op
from ..discord_api import ApiError, DiscordAPI
from ..models import Account, ConnState
from ..ops import OpKind
from ..presence_manager import PresenceManager
from .accounts import AccountsTable
from .edit import EditRequest, EditScreen
from .log import LogPane
from .modals import AddTokenScreen, ConfirmScreen, PassphraseScreen


class ManagerApp(App):
    TITLE = "Discord Account Manager"
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    AccountsTable { height: 2fr; border: round $accent; }
    LogPane { height: 1fr; border: round $primary; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("e", "edit", "Edit op"),
        ("t", "add_token", "Add token"),
        ("d", "del_token", "Delete"),
        ("space", "toggle", "Toggle sel"),
        ("a", "select_all", "All"),
        ("n", "select_none", "None"),
        ("r", "refresh_whoami", "Refresh"),
    ]

    def __init__(self):
        super().__init__()
        self.accounts: list[Account] = []
        self.passphrase: str | None = None
        self.presence = PresenceManager(on_state=self._on_conn_state)
        self._table: AccountsTable | None = None
        self._log: LogPane | None = None

    # ---- layout ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            self._table = AccountsTable(self.accounts)
            self._log = LogPane()
            yield self._table
            yield self._log
        yield Footer()

    async def on_mount(self) -> None:
        self.push_screen(PassphraseScreen(new_vault=not vault.vault_exists()), self._after_pass)

    # ---- unlock ----------------------------------------------------------

    async def _after_pass(self, passphrase: str | None) -> None:
        if passphrase is None:
            self.exit()
            return
        if not vault.verify_passphrase(passphrase):
            self._log.fail("vault", "wrong passphrase")
            self.push_screen(PassphraseScreen(new_vault=False), self._after_pass)
            return
        self.passphrase = passphrase
        self.accounts.clear()
        self.accounts.extend(vault.load(passphrase))
        self._table.accounts = self.accounts
        self._table.refresh_rows()
        self._log.info(f"vault unlocked: {len(self.accounts)} account(s)")
        # Bring everyone online, then refresh identities.
        self.run_worker(self.presence.start_all(self.accounts), exclusive=False)
        for acc in self.accounts:
            self.run_worker(self._whoami(acc), exclusive=False)

    def _persist(self) -> None:
        if self.passphrase is not None:
            vault.save(self.accounts, self.passphrase)

    # ---- gateway state callback -----------------------------------------

    def _on_conn_state(self, key: str, state: ConnState) -> None:
        for acc in self.accounts:
            if acc.label == key:
                acc.conn_state = state
                if self._table is not None:
                    self._table.refresh_rows()
                break

    # ---- identity refresh -----------------------------------------------

    async def _whoami(self, acc: Account) -> None:
        try:
            async with DiscordAPI(acc.token) as api:
                me = await api.whoami()
            acc.user_id = me.get("id")
            acc.username = me.get("username")
            acc.global_name = me.get("global_name")
        except ApiError as exc:
            acc.last_result = exc.message
        if self._table is not None:
            self._table.refresh_rows()

    # ---- selection actions ----------------------------------------------

    def action_toggle(self) -> None:
        self._table.toggle_cursor()

    def action_select_all(self) -> None:
        self._table.select_all(True)

    def action_select_none(self) -> None:
        self._table.select_all(False)

    async def action_refresh_whoami(self) -> None:
        for acc in self._table.selected_accounts():
            self.run_worker(self._whoami(acc), exclusive=False)

    # ---- token management ------------------------------------------------

    async def action_add_token(self) -> None:
        self.push_screen(AddTokenScreen(), self._after_add_token)

    async def _after_add_token(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        label, token = result
        if any(a.label == label for a in self.accounts):
            self._log.fail("add", f"label '{label}' already exists")
            return
        # Validate before persisting.
        try:
            async with DiscordAPI(token) as api:
                me = await api.whoami()
        except ApiError as exc:
            self._log.fail("add", f"token rejected: {exc.message}")
            return
        acc = Account(label=label, token=token)
        acc.user_id = me.get("id")
        acc.username = me.get("username")
        acc.global_name = me.get("global_name")
        self.accounts.append(acc)
        self._persist()
        self._table.refresh_rows()
        self._log.ok("add", f"{acc.display} added")
        self.presence.add(acc)

    async def action_del_token(self) -> None:
        acc = self._table.cursor_account
        if acc is None:
            return
        confirm = await self.push_screen_wait(ConfirmScreen(f"Delete '{acc.label}'?"))
        if not confirm:
            return
        await self.presence.remove(acc)
        self.accounts.remove(acc)
        self._persist()
        self._table.refresh_rows()
        self._log.info(f"{acc.label} removed")

    # ---- run an op -------------------------------------------------------

    async def action_edit(self) -> None:
        if not self.accounts:
            self._log.fail("edit", "no accounts")
            return
        req = await self.push_screen_wait(EditScreen())
        if req is None:
            return
        targets = self._resolve_scope(req)
        if not targets:
            self._log.fail("edit", "no target accounts for scope")
            return
        self._log.info(f"{req.kind.value}: running on {len(targets)} account(s)…")
        self.run_worker(self._run_batch(req, targets), exclusive=False)

    def _resolve_scope(self, req: EditRequest) -> list[Account]:
        if req.scope == "all":
            return list(self.accounts)
        if req.scope == "current":
            acc = self._table.cursor_account
            return [acc] if acc else []
        return self._table.selected_accounts()

    async def _run_batch(self, req: EditRequest, targets: list[Account]) -> None:
        async for who, ok, msg in run_op(req.kind, req.value, targets, self.presence):
            self._log.result(who, ok, msg)
            self._table.refresh_rows()
        self._persist_presence(req, targets)
        self._log.info(f"{req.kind.value}: done")

    def _persist_presence(self, req: EditRequest, targets: list[Account]) -> None:
        """Save presence/custom-status edits so the daemon restores them on restart."""
        value = req.value.strip()
        for acc in targets:
            if req.kind is OpKind.PRESENCE:
                presence_config.set_for(acc.label, status=value)
            elif req.kind is OpKind.CUSTOM_STATUS:
                presence_config.set_for(acc.label, custom=value)

    # ---- shutdown --------------------------------------------------------

    async def action_quit(self) -> None:
        await self.presence.stop_all()
        self.exit()
