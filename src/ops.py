"""High-level operations mapping a chosen action + value to an API call.

HTTP ops go through `DiscordAPI`. The presence op (live dot + custom status) is
handled by the presence manager over the gateway, not here -- see `presence_manager`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .discord_api import DiscordAPI
from .models import Account, CustomStatus


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
            cs = CustomStatus.parse(value)
            await api.set_settings_custom_status(cs.text, cs.emoji_name, cs.emoji_id)
            return "custom status updated"
        raise ValueError(f"{kind} is not an HTTP op")


async def pull_custom_status(account: Account) -> CustomStatus:
    """Read the account's current custom status from Discord (exact emoji included)."""
    async with DiscordAPI(account.token) as api:
        settings = await api.get_settings()
    return CustomStatus.from_settings(settings.get("custom_status")) or CustomStatus()
