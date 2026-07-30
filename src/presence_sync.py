"""Startup reconcile: adopt a presence change made while nothing of ours was running.

The gateway reports live changes (see `gateway._observe_presence`), but only while a
socket is open. Set a status from your phone with the daemon down and nobody sees it --
`presence.json` would then re-apply its stale value on the next start.

So at start we read what Discord actually has and compare it against `seen`, the snapshot
of what its settings said last time. A *difference from the snapshot* means someone else
changed it, and we adopt it. Comparing against the configured value instead would be
wrong: the two legitimately differ right after we set something ourselves.
"""
from __future__ import annotations

import logging

from . import presence_config
from .discord_api import ApiError
from .models import Account, CustomStatus
from .ops import fetch_presence

log = logging.getLogger(__name__)


async def reconcile(account: Account) -> tuple[str | None, CustomStatus | None]:
    """Return the (status, custom) fields Discord changed behind our back.

    `None` for a field means "nothing to adopt" -- the same convention the gateway uses,
    so the result feeds straight into an `on_presence` callback. An empty CustomStatus is
    a real value meaning "cleared". Always refreshes the stored snapshot.
    """
    try:
        status, custom = await fetch_presence(account)
    except (ApiError, OSError) as exc:
        # Never let a failed read stop the account from connecting.
        log.warning("presence reconcile failed for %s: %s", account.label, exc)
        return None, None

    seen = presence_config.seen_for(account.label)
    presence_config.set_seen(account.label, status, custom)
    if seen is None:
        # First run for this account (or an entry predating the snapshot). Nothing to
        # compare against, and guessing risks discarding a status the user set here.
        return None, None

    changed_status = status if status is not None and status != seen["status"] else None
    changed_custom = custom if custom != seen["custom"] else None
    return changed_status, changed_custom
