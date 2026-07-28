"""High-level operations mapping a chosen action + value to an API call.

HTTP ops go through `DiscordAPI`. The presence op (live dot + custom status) is
handled by the presence manager over the gateway, not here -- see `presence_manager`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .discord_api import DiscordAPI
from .models import Account

# A custom/Nitro emoji as typed in Discord: <:name:id> or animated <a:name:id>.
_CUSTOM_EMOJI = re.compile(r"^<a?:([A-Za-z0-9_]+):(\d+)>\s*(.*)$", re.DOTALL)


class OpKind(str, Enum):
    BIO = "bio"
    GLOBAL_NAME = "global_name"
    USERNAME = "username"
    AVATAR = "avatar"
    BANNER = "banner"
    CUSTOM_STATUS = "custom_status"  # persisted text (also pushed live via gateway)
    PRESENCE = "presence"            # online/idle/dnd/invisible -- gateway-driven


@dataclass(frozen=True)
class OpSpec:
    kind: OpKind
    label: str
    value_hint: str            # what the user types
    gateway: bool = False      # True => routed through presence_manager, not HTTP


OP_SPECS: list[OpSpec] = [
    OpSpec(OpKind.CUSTOM_STATUS, "Custom status", "text | 🔥 text | <:name:id> [text]"),
    OpSpec(OpKind.PRESENCE, "Presence (dot)", "online | idle | dnd | invisible", gateway=True),
    OpSpec(OpKind.BIO, "Bio (About Me)", "bio text"),
    OpSpec(OpKind.GLOBAL_NAME, "Display name", "new display name"),
    OpSpec(OpKind.USERNAME, "Username", "new_username|account_password"),
    OpSpec(OpKind.AVATAR, "Avatar", "path to image file"),
    OpSpec(OpKind.BANNER, "Banner (Nitro)", "path to image file"),
]

OP_BY_KIND = {spec.kind: spec for spec in OP_SPECS}


async def run_http_op(account: Account, kind: OpKind, value: str) -> str:
    """Execute one HTTP op against one account. Returns a short result string.

    Raises ApiError on failure (caller decides how to surface it).
    """
    async with DiscordAPI(account.token) as api:
        if kind is OpKind.BIO:
            await api.set_bio(value)
            return "bio updated"
        if kind is OpKind.GLOBAL_NAME:
            await api.set_global_name(value)
            return "display name updated"
        if kind is OpKind.USERNAME:
            username, _, password = value.partition("|")
            if not password:
                raise ValueError("username op needs 'new_username|account_password'")
            await api.set_username(username.strip(), password)
            return "username updated"
        if kind is OpKind.AVATAR:
            await api.set_avatar(value.strip())
            return "avatar updated"
        if kind is OpKind.BANNER:
            await api.set_banner(value.strip())
            return "banner updated"
        if kind is OpKind.CUSTOM_STATUS:
            text, emoji_name, emoji_id = _split_status(value)
            await api.set_settings_custom_status(text, emoji_name, emoji_id)
            return "custom status updated"
        raise ValueError(f"{kind} is not an HTTP op")


def _split_status(value: str) -> tuple[str, str | None, str | None]:
    """Split a typed custom status into (text, emoji_name, emoji_id).

    Handles a leading unicode emoji ('🔥 grinding' -> ('grinding', '🔥', None), or
    emoji-only '🔥' -> ('', '🔥', None)) and a custom/Nitro emoji token
    ('<:pepe:123> hi' -> ('hi', 'pepe', '123')). Plain text -> (text, None, None).
    """
    value = value.strip()
    if not value:
        return "", None, None
    m = _CUSTOM_EMOJI.match(value)
    if m:
        name, emoji_id, rest = m.group(1), m.group(2), m.group(3)
        return rest.strip(), name, emoji_id
    first, _, rest = value.partition(" ")
    # A non-ascii leading token is a unicode emoji (with or without trailing text).
    if not first.isascii():
        return rest.strip(), first, None
    return value, None, None
