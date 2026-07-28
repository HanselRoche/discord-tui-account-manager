"""Async Discord HTTP client (one per account), rate-limit aware.

Uses the raw user-token API (no "Bot " prefix). Sends realistic client headers
(User-Agent + X-Super-Properties) so requests look like the official web client.
"""
from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO

import httpx
from PIL import Image

API_BASE = "https://discord.com/api/v9"

# Mimic a recent desktop web client. Bump these periodically if requests start failing.
_CLIENT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_SUPER_PROPS = {
    "os": "Linux",
    "browser": "Chrome",
    "device": "",
    "system_locale": "en-US",
    "browser_user_agent": _CLIENT_UA,
    "browser_version": "124.0.0.0",
    "os_version": "",
    "referrer": "",
    "referring_domain": "",
    "release_channel": "stable",
    "client_build_number": 300000,
}


def _super_properties_header() -> str:
    return base64.b64encode(json.dumps(_SUPER_PROPS).encode("utf-8")).decode("utf-8")


class ApiError(Exception):
    """A non-retryable API failure (bad token, validation error, etc)."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


class DiscordAPI:
    """Thin async wrapper around the endpoints this tool needs."""

    _MAX_RETRIES = 4

    def __init__(self, token: str):
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={
                "Authorization": token,
                "User-Agent": _CLIENT_UA,
                "X-Super-Properties": _super_properties_header(),
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "DiscordAPI":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        """Core request with 429 backoff. Raises ApiError on 4xx (except 429)."""
        for attempt in range(self._MAX_RETRIES):
            resp = await self._client.request(method, path, json=json_body)

            if resp.status_code == 429:
                # Rate limited: honor retry_after, then retry.
                try:
                    retry_after = float(resp.json().get("retry_after", 1.0))
                except Exception:
                    retry_after = float(resp.headers.get("Retry-After", 1.0))
                await asyncio.sleep(retry_after + 0.25)
                continue

            if resp.status_code in (401, 403):
                raise ApiError(resp.status_code, "Token dead or missing permission.")

            if resp.status_code >= 400:
                raise ApiError(resp.status_code, _extract_error(resp))

            if not resp.content:
                return {}
            return resp.json()

        raise ApiError(429, "Rate limited: exhausted retries.")

    # ---- endpoints -------------------------------------------------------

    async def whoami(self) -> dict:
        return await self._request("GET", "/users/@me")

    async def get_settings(self) -> dict:
        """Current status + custom status (GET /users/@me/settings)."""
        return await self._request("GET", "/users/@me/settings")

    async def set_bio(self, bio: str) -> dict:
        return await self._request("PATCH", "/users/@me/profile", {"bio": bio})

    async def set_global_name(self, name: str) -> dict:
        return await self._request("PATCH", "/users/@me", {"global_name": name})

    async def set_username(self, username: str, password: str) -> dict:
        return await self._request(
            "PATCH", "/users/@me", {"username": username, "password": password}
        )

    async def set_avatar(self, image_path: str) -> dict:
        return await self._request(
            "PATCH", "/users/@me", {"avatar": _encode_image(image_path)}
        )

    async def set_banner(self, image_path: str) -> dict:
        return await self._request(
            "PATCH", "/users/@me", {"banner": _encode_image(image_path)}
        )

    async def set_settings_status(self, status: str) -> dict:
        """Persist the default status (visible next connect). Live dot = gateway."""
        return await self._request("PATCH", "/users/@me/settings", {"status": status})

    async def set_settings_custom_status(
        self, text: str, emoji_name: str | None = None, emoji_id: str | None = None
    ) -> dict:
        """Set the custom status. Emoji-only (blank text) is allowed; a null object is
        only sent when text and emoji are all empty (an explicit clear)."""
        if not (text or emoji_name or emoji_id):
            cs: dict | None = None
        else:
            cs = {"text": text or None}
            if emoji_name:
                cs["emoji_name"] = emoji_name
            if emoji_id:
                cs["emoji_id"] = emoji_id
        return await self._request(
            "PATCH", "/users/@me/settings", {"custom_status": cs}
        )


def _extract_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return resp.text[:200] or "Unknown error"
    if isinstance(data, dict):
        return data.get("message") or json.dumps(data)[:200]
    return str(data)[:200]


def _encode_image(path: str) -> str:
    """Load an image, normalize to PNG, return a data: URI Discord accepts."""
    with Image.open(path) as img:
        img = img.convert("RGBA")
        buf = BytesIO()
        img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"
