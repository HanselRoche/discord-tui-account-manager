"""Owns one gateway connection per account and keeps them all online.

Started at launch: every account gets a `GatewayConnection` (staggered to avoid an
identical login burst). Exposes `set_presence` so the TUI can change the dot / custom
status live over the gateway. Connection state changes flow back to a callback so the
accounts table can reflect online / connecting / dead.
"""
from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable

from .gateway import GatewayConnection
from .models import Account, ConnState

StateCallback = Callable[[str, ConnState], Awaitable[None] | None]
PresenceLookup = Callable[[str], dict]


class PresenceManager:
    def __init__(self, on_state: StateCallback | None = None):
        self._conns: dict[str, GatewayConnection] = {}
        self._on_state = on_state

    def _key(self, account: Account) -> str:
        # Label is stable and enforced-unique at add time; the gateway needs a key
        # before whoami/READY tells us the user_id, so key on label throughout.
        return account.label

    async def start_all(
        self, accounts: list[Account], presence_for: PresenceLookup | None = None
    ) -> None:
        """Bring every account online, staggering connects.

        `presence_for(label) -> {"status", "custom"}` optionally sets each account's
        initial presence (used by the daemon to restore stored status). Defaults to
        online / no custom status.
        """
        for i, acc in enumerate(accounts):
            p = presence_for(acc.label) if presence_for else None
            self.add(
                acc,
                status=(p or {}).get("status"),
                custom=(p or {}).get("custom"),
            )
            if i < len(accounts) - 1:
                await asyncio.sleep(random.uniform(0.5, 2.5))

    def add(self, account: Account, status: str | None = None, custom: str | None = None) -> None:
        """Start (or restart) a connection for one account."""
        key = self._key(account)
        if key in self._conns:
            return
        conn = GatewayConnection(
            account_id=key,
            token=account.token,
            status=status,
            custom_status=custom,
            on_state=self._on_state,
        )
        self._conns[key] = conn
        conn.start()

    async def remove(self, account: Account) -> None:
        key = self._key(account)
        conn = self._conns.pop(key, None)
        if conn is not None:
            await conn.stop()

    def state_of(self, account: Account) -> ConnState:
        conn = self._conns.get(self._key(account))
        return conn.state if conn else ConnState.OFFLINE

    async def set_presence(
        self,
        accounts: list[Account],
        status: str | None = None,
        custom: str | None = None,
    ) -> list[tuple[str, bool, str]]:
        """Push a live presence change to the given accounts. Returns per-account results."""
        results: list[tuple[str, bool, str]] = []
        for acc in accounts:
            conn = self._conns.get(self._key(acc))
            if conn is None:
                results.append((acc.display, False, "not connected"))
                continue
            if conn.state is ConnState.DEAD:
                results.append((acc.display, False, "token dead"))
                continue
            try:
                await conn.update_presence(status=status, custom=custom)
                what = status or ""
                if custom is not None:
                    what = f"{what} / {custom}".strip(" /")
                results.append((acc.display, True, f"presence -> {what}"))
            except Exception as exc:  # noqa: BLE001 - surface any send failure
                results.append((acc.display, False, str(exc)))
        return results

    async def stop_all(self) -> None:
        await asyncio.gather(*(c.stop() for c in self._conns.values()), return_exceptions=True)
        self._conns.clear()
