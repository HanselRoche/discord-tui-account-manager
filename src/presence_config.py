"""Per-account presence config (which status each account should hold).

Plain JSON, not secret (no tokens here) — unlike the encrypted vault. Lets the daemon
restore each account's status/custom-status across restarts, and lets the TUI persist a
presence change so a later daemon start matches it.

Shape: { "<label>": {"status": "dnd", "custom": "text" | null, "afk": true|false|null,
                     "seen": {"status": ..., "custom": ...} | null} }

`seen` is bookkeeping, not intent: what Discord's own settings said the last time we
looked. Startup compares against it to tell "the phone changed this while we were down"
(adopt) from "we set this ourselves last run" (keep). See presence_sync.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import CustomStatus

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "presence.json"

# None = "not configured" -> the gateway preserves whatever the account already shows
# (e.g. a custom status / dot set from the phone) instead of forcing online / blank.
# `afk` is the exception: None resolves to the gateway default (True), which keeps Discord
# pushing pings/DMs to your phone. It is invisible to other users.
DEFAULT = {"status": None, "custom": None, "afk": None, "seen": None}


def load() -> dict[str, dict]:
    """Return the full config map. Empty dict if none / unreadable."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def for_label(label: str) -> dict:
    """Presence for one account. `custom` is a CustomStatus (or None to preserve)."""
    entry = load().get(label)
    if not entry:
        return {"status": None, "custom": None, "afk": None}
    return {
        "status": entry.get("status"),
        "custom": CustomStatus.from_config(entry.get("custom")),
        "afk": entry.get("afk"),
    }


def seen_for(label: str) -> dict | None:
    """What Discord's settings last said for one account, or None if never recorded.

    None is meaningful: with no snapshot there is no way to tell an external change from
    our own, so callers must not adopt anything on it.
    """
    entry = load().get(label) or {}
    seen = entry.get("seen")
    if not isinstance(seen, dict):
        return None
    return {
        "status": seen.get("status"),
        "custom": CustomStatus.from_config(seen.get("custom")) or CustomStatus(),
    }


def set_seen(label: str, status: str | None, custom: CustomStatus | None) -> None:
    """Record what Discord's settings currently say, so the next start can spot a change.

    Merges like `set_for`: a None field is left at its stored value, which lets a caller
    that only touched one of the two record just that one.
    """
    cfg = load()
    entry = cfg.get(label, dict(DEFAULT))
    seen = entry.get("seen")
    seen = dict(seen) if isinstance(seen, dict) else {"status": None, "custom": None}
    if status is not None:
        seen["status"] = status
    if custom is not None:
        seen["custom"] = None if custom.is_empty else custom.to_config()
    entry["seen"] = seen
    cfg[label] = entry
    _write(cfg)


def set_for(
    label: str,
    status: str | None = None,
    custom: CustomStatus | None = None,
    afk: bool | None = None,
) -> None:
    """Merge a change for one account and persist immediately.

    Only non-None fields overwrite; the rest keep their stored value. `custom` is
    serialized (a plain string for text/unicode, a dict for a custom emoji). An *empty*
    CustomStatus means "cleared" and is stored as null, so a later start preserves the
    blank instead of re-applying an old status.
    """
    cfg = load()
    entry = cfg.get(label, dict(DEFAULT))
    if status is not None:
        entry["status"] = status
    if custom is not None:
        entry["custom"] = None if custom.is_empty else custom.to_config()
    if afk is not None:
        entry["afk"] = afk
    cfg[label] = entry
    _write(cfg)


def _write(cfg: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    tmp.replace(CONFIG_PATH)
