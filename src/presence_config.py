"""Per-account presence config (which status each account should hold).

Plain JSON, not secret (no tokens here) — unlike the encrypted vault. Lets the daemon
restore each account's status/custom-status across restarts, and lets the TUI persist a
presence change so a later daemon start matches it.

Shape: { "<label>": {"status": "dnd", "custom": "text" | null} }
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "presence.json"

DEFAULT = {"status": "online", "custom": None}


def load() -> dict[str, dict]:
    """Return the full config map. Empty dict if none / unreadable."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def for_label(label: str) -> dict:
    """Presence for one account, falling back to DEFAULT."""
    entry = load().get(label)
    if not entry:
        return dict(DEFAULT)
    return {"status": entry.get("status", "online"), "custom": entry.get("custom")}


def set_for(label: str, status: str | None = None, custom: str | None = None) -> None:
    """Merge a change for one account and persist immediately.

    Only non-None fields overwrite; the rest keep their stored value.
    """
    cfg = load()
    entry = cfg.get(label, dict(DEFAULT))
    if status is not None:
        entry["status"] = status
    if custom is not None:
        entry["custom"] = custom
    cfg[label] = entry
    _write(cfg)


def _write(cfg: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    tmp.replace(CONFIG_PATH)
