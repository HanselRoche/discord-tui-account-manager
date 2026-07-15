"""Run an operation across accounts, sequentially with jittered delays.

Sequential + jitter avoids an identical-burst fingerprint that mass-edits would
otherwise produce. Results are yielded one account at a time so the TUI log can
stream them live. Presence ops are delegated to the presence manager (gateway).
"""
from __future__ import annotations

import asyncio
import random
from typing import AsyncIterator

from .discord_api import ApiError
from .models import Account
from .ops import OpKind, run_http_op
from .presence_manager import PresenceManager

# Delay between accounts in a batch: base + up to `jitter` extra seconds.
BASE_DELAY = 2.0
JITTER = 3.0


async def run_op(
    kind: OpKind,
    value: str,
    accounts: list[Account],
    presence: PresenceManager,
) -> AsyncIterator[tuple[str, bool, str]]:
    """Yield (account_display, ok, message) for each account as it completes."""
    if kind is OpKind.PRESENCE:
        # Live dot change goes over the gateway; no per-account HTTP delay needed.
        for res in await presence.set_presence(accounts, status=value.strip()):
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

        # For a custom-status HTTP change, also push it live over the gateway.
        if kind is OpKind.CUSTOM_STATUS:
            await presence.set_presence([acc], custom=value.strip())

        if i < len(accounts) - 1:
            await asyncio.sleep(BASE_DELAY + random.uniform(0, JITTER))
