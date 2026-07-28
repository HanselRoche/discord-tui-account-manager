"""Run an operation across accounts, sequentially with jittered delays.

Sequential + jitter avoids an identical-burst fingerprint that mass-edits would
otherwise produce. Results are yielded one account at a time so the TUI log can
stream them live. Presence ops are delegated to the presence manager (gateway).
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
        # Live dot change goes over the gateway; no per-account HTTP delay needed.
        for res in await presence.set_presence(accounts, status=value.strip()):
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
