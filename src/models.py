"""Data models for accounts and presence."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnState(str, Enum):
    """Gateway connection state for an account."""

    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    DEAD = "dead"  # token rejected (401/4004)


# Valid Discord presence statuses (the visible dot).
PRESENCE_STATUSES = ("online", "idle", "dnd", "invisible")


@dataclass
class Account:
    """A single Discord account managed by user token.

    `token` is the raw user token. Everything else is cached info populated
    after a `GET /users/@me` (whoami) or the gateway READY event.
    """

    label: str
    token: str
    # Cached identity (filled after whoami / READY)
    user_id: str | None = None
    username: str | None = None
    global_name: str | None = None
    # Cached Discord presence (filled after get_settings). Runtime cache, not persisted.
    status: str | None = None          # online | idle | dnd | invisible | offline
    custom_status: str | None = None   # rendered custom-status text (emoji + text)
    # Runtime state (not persisted)
    selected: bool = False
    conn_state: ConnState = field(default=ConnState.OFFLINE)
    last_result: str = ""

    @property
    def display(self) -> str:
        """Best human name for the account."""
        return self.global_name or self.username or self.label

    @property
    def ign(self) -> str:
        """Display name + @username, e.g. 'Hansel (@hansel)'."""
        if self.username:
            if self.global_name:
                return f"{self.global_name} (@{self.username})"
            return f"@{self.username}"
        return self.label

    @property
    def status_display(self) -> str:
        """Discord status dot + custom text, e.g. 'dnd · 🔥 grinding'. '—' if unknown."""
        parts = [p for p in (self.status, self.custom_status) if p]
        return " · ".join(parts) if parts else "—"

    def to_json(self) -> dict:
        """Only the persistable fields go to the encrypted vault."""
        return {"label": self.label, "token": self.token}

    @classmethod
    def from_json(cls, d: dict) -> "Account":
        return cls(label=d["label"], token=d["token"])
