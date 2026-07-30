"""High-level operations mapping a chosen action + value to an API call.

HTTP ops go through `DiscordAPI`. Presence (dot + custom status) is written here too,
because Discord stores it account-level; the *live* half of it -- making the change show
immediately on an open session -- belongs to `presence_manager` over the gateway.
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
        if kind is OpKind.PRESENCE:
            # Account-level, so the dot survives this process and reaches other devices.
            # The live dot still goes over the gateway; see batch.run_op.
            await api.set_settings_status(value.strip())
            return "presence updated"
        raise ValueError(f"{kind} is not an HTTP op")


async def fetch_presence(account: Account) -> tuple[str | None, CustomStatus]:
    """Read the account's presence as Discord has it stored: (dot, custom status).

    This is the account-level setting, not per-session state -- it is what a phone sets
    and what survives every client disconnecting. An empty CustomStatus means "none set".
    """
    async with DiscordAPI(account.token) as api:
        settings = await api.get_settings()
    custom = CustomStatus.from_settings(settings.get("custom_status")) or CustomStatus()
    return settings.get("status"), custom


async def pull_custom_status(account: Account) -> CustomStatus:
    """Read the account's current custom status from Discord (exact emoji included)."""
    _, custom = await fetch_presence(account)
    return custom
