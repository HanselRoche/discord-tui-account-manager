"""Data models for accounts and presence."""
from __future__ import annotations

import re
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

# A custom/Nitro emoji as typed in Discord: <:name:id> or animated <a:name:id>.
_CUSTOM_EMOJI = re.compile(r"^<(a)?:([A-Za-z0-9_]+):(\d+)>\s*(.*)$", re.DOTALL)


@dataclass(frozen=True)
class CustomStatus:
    """A custom status: text plus an optional emoji (unicode or custom/Nitro).

    Single source of truth for parsing what the user types, rendering it for display,
    building the gateway type-4 activity, and (de)serializing it for presence.json.
    """

    text: str = ""
    emoji_name: str | None = None   # unicode char OR custom-emoji shortcode
    emoji_id: str | None = None     # set only for a custom/Nitro emoji
    animated: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.text or self.emoji_name or self.emoji_id)

    @classmethod
    def parse(cls, value: str) -> "CustomStatus":
        """Parse a typed value: '🔥 hi', '🔥', '<:pepe:123> hi', '<a:wave:4>', 'hi', ''."""
        value = (value or "").strip()
        if not value:
            return cls()
        m = _CUSTOM_EMOJI.match(value)
        if m:
            animated, name, emoji_id, rest = m.group(1), m.group(2), m.group(3), m.group(4)
            return cls(rest.strip(), name, emoji_id, bool(animated))
        first, _, rest = value.partition(" ")
        # A non-ascii leading token is a unicode emoji (with or without trailing text).
        if not first.isascii():
            return cls(rest.strip(), first)
        return cls(value)

    @classmethod
    def from_settings(cls, cs: object) -> "CustomStatus | None":
        """Build from a /users/@me/settings `custom_status` object (or None)."""
        if not isinstance(cs, dict):
            return None
        out = cls(
            text=(cs.get("text") or "").strip(),
            emoji_name=cs.get("emoji_name"),
            emoji_id=cs.get("emoji_id"),
        )
        return None if out.is_empty else out

    @classmethod
    def from_activity(cls, activity: dict) -> "CustomStatus | None":
        """Build from a gateway type-4 activity (has `state` + optional `emoji`)."""
        emoji = activity.get("emoji") or {}
        out = cls(
            text=(activity.get("state") or "").strip(),
            emoji_name=emoji.get("name"),
            emoji_id=emoji.get("id"),
            animated=bool(emoji.get("animated")),
        )
        return None if out.is_empty else out

    def activity_emoji(self) -> dict | None:
        """The `emoji` field for a gateway type-4 activity (None if no emoji)."""
        if not self.emoji_name and not self.emoji_id:
            return None
        emoji: dict = {"name": self.emoji_name}
        if self.emoji_id:
            emoji["id"] = self.emoji_id
            emoji["animated"] = self.animated
        return emoji

    def display(self) -> str:
        """Human text for the TUI: ':name: text' (custom) or 'emoji text' (unicode)."""
        if self.emoji_id and self.emoji_name:
            emoji = f":{self.emoji_name}:"
        else:
            emoji = self.emoji_name
        return f"{emoji} {self.text}".strip() if emoji else self.text

    def to_config(self) -> str | dict:
        """Serialize for presence.json: a plain string when there's no custom emoji."""
        if not self.emoji_id and not self.animated:
            # Text-only or unicode-emoji: a string round-trips through parse().
            return self.display()
        d: dict = {"text": self.text, "emoji_name": self.emoji_name, "emoji_id": self.emoji_id}
        if self.animated:
            d["animated"] = True
        return d

    @classmethod
    def from_config(cls, v: object) -> "CustomStatus | None":
        """Inverse of to_config: accept a legacy string or a structured dict."""
        if v is None:
            return None
        if isinstance(v, str):
            out = cls.parse(v)
            return None if out.is_empty else out
        if isinstance(v, dict):
            out = cls(
                text=(v.get("text") or "").strip(),
                emoji_name=v.get("emoji_name"),
                emoji_id=v.get("emoji_id"),
                animated=bool(v.get("animated")),
            )
            return None if out.is_empty else out
        return None


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
