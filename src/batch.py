"""Run an operation across accounts, sequentially with jittered delays.

Sequential + jitter avoids an identical-burst fingerprint that mass-edits would
otherwise produce. Results are yielded one account at a time so the TUI log can
stream them live. Presence ops are written account-wide over HTTP *and* pushed live
through the presence manager (gateway) -- the gateway alone is session-scoped.
"""
from __future__ import annotations

import asyncio
import random
from typing import AsyncIterator

from . import presence_config
from .discord_api import ApiError
from .models import Account, CustomStatus
from .ops import OpKind, pull_custom_status, run_http_op
from .presence_manager import PresenceManager

# Delay between accounts in a batch: base + up to `jitter` extra seconds.
BASE_DELAY = 2.0
JITTER = 3.0


async def run_op(
    kind: OpKind,
    value: str,
    accounts: list[Account],
    presence: PresenceManager,
    source: str = "tui",
) -> AsyncIterator[tuple[str, bool, str]]:
    """Yield (account_display, ok, message) for each account as it completes.

    `source` applies to CUSTOM_STATUS only: "tui" uses the typed value; "discord"
    (or a blank value) pulls the account's current custom status from Discord.
    """
    if kind is OpKind.PRESENCE:
        async for res in _run_presence(value, accounts, presence):
            yield res
        return

    if kind is OpKind.CUSTOM_STATUS:
        pull = source == "discord" or not value.strip()
        async for res in _run_custom_status(value, accounts, presence, pull):
            yield res
        return

    for i, acc in enumerate(accounts):
        try:
            msg = await run_http_op(acc, kind, value)
            acc.last_result = msg
            yield (acc.display, True, msg)
        except ApiError as exc:
            acc.last_result = exc.message
            yield (acc.display, False, exc.message)
        except (ValueError, FileNotFoundError, OSError) as exc:
            acc.last_result = str(exc)
            yield (acc.display, False, str(exc))

        if i < len(accounts) - 1:
            await asyncio.sleep(BASE_DELAY + random.uniform(0, JITTER))


async def _run_presence(
    value: str,
    accounts: list[Account],
    presence: PresenceManager,
) -> AsyncIterator[tuple[str, bool, str]]:
    """Set the dot: persist it account-wide over HTTP, then push it live over the gateway.

    The HTTP half is what makes it outlive this process and reach other devices -- the
    gateway alone is session-scoped. Recording it as `seen` matters too: without that, the
    next start would read it back from Discord and mistake our own change for one made
    from another device.
    """
    status = value.strip()
    for i, acc in enumerate(accounts):
        try:
            await run_http_op(acc, OpKind.PRESENCE, status)
            presence_config.set_seen(acc.label, status, None)
            acc.status = status
            # The gateway push only makes it show *now*; a failure here (account not
            # connected) doesn't undo the account-level change above.
            live = await presence.set_presence([acc], status=status)
            note = "" if all(ok for _, ok, _ in live) else " (not live: no connection)"
            msg = f"presence -> {status}{note}"
            acc.last_result = msg
            yield (acc.display, True, msg)
        except ApiError as exc:
            acc.last_result = exc.message
            yield (acc.display, False, exc.message)
        except (ValueError, FileNotFoundError, OSError) as exc:
            acc.last_result = str(exc)
            yield (acc.display, False, str(exc))

        if i < len(accounts) - 1:
            await asyncio.sleep(BASE_DELAY + random.uniform(0, JITTER))


async def _run_custom_status(
    value: str,
    accounts: list[Account],
    presence: PresenceManager,
    pull: bool,
) -> AsyncIterator[tuple[str, bool, str]]:
    """Set (typed) or pull-from-Discord each account's custom status, then apply it
    live over the gateway, cache it for display, and persist the exact CustomStatus."""
    for i, acc in enumerate(accounts):
        try:
            if pull:
                cs = await pull_custom_status(acc)
                msg = f"custom status <- Discord: {cs.display() or 'none'}"
            else:
                cs = CustomStatus.parse(value)
                # HTTP persists the setting; the gateway push below (parsed) carries
                # text + emoji, not the raw <:name:id> token.
                await run_http_op(acc, OpKind.CUSTOM_STATUS, value)
                msg = f"custom status -> {cs.display() or 'none'}"
            await presence.set_presence([acc], custom=cs)
            presence_config.set_for(acc.label, custom=cs)
            # Both branches leave Discord holding `cs`, so record it as seen -- otherwise
            # the next start reads it back and calls our own change an external one.
            presence_config.set_seen(acc.label, None, cs)
            acc.custom_status = cs.display() or None
            acc.last_result = msg
            yield (acc.display, True, msg)
        except ApiError as exc:
            acc.last_result = exc.message
            yield (acc.display, False, exc.message)
        except (ValueError, FileNotFoundError, OSError) as exc:
            acc.last_result = str(exc)
            yield (acc.display, False, str(exc))

        if i < len(accounts) - 1:
            await asyncio.sleep(BASE_DELAY + random.uniform(0, JITTER))
