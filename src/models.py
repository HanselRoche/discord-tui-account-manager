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
    # Runtime state (not persisted)
    selected: bool = False
    conn_state: ConnState = field(default=ConnState.OFFLINE)
    last_result: str = ""

    @property
    def display(self) -> str:
        """Best human name for the account."""
        return self.global_name or self.username or self.label

    def to_json(self) -> dict:
        """Only the persistable fields go to the encrypted vault."""
        return {"label": self.label, "token": self.token}

    @classmethod
    def from_json(cls, d: dict) -> "Account":
        return cls(label=d["label"], token=d["token"])
