"""Persistent Discord gateway connection per account.

Holds a WebSocket open so the account shows online. Handles the full lifecycle:
HELLO -> heartbeat loop -> IDENTIFY -> READY, with zombie detection, exponential
backoff, and RESUME on reconnect. Presence (dot + custom status) is pushed live via
op 3 PRESENCE UPDATE.

Gateway opcodes used:
  0  DISPATCH        (server -> us; READY, RESUMED, ...)
  1  HEARTBEAT
  2  IDENTIFY
  3  PRESENCE UPDATE
  6  RESUME
  7  RECONNECT       (server asks us to reconnect)
  9  INVALID SESSION
  10 HELLO
  11 HEARTBEAT ACK
"""
from __future__ import annotations

import asyncio
import json
import random
from typing import Awaitable, Callable

import websockets

from .discord_api import _CLIENT_UA
from .models import ConnState, CustomStatus

GATEWAY_URL = "wss://gateway.discord.gg/?v=9&encoding=json"

# Non-recoverable close codes (bad token, auth failed, etc). Don't retry these.
_FATAL_CLOSE_CODES = {4004, 4010, 4011, 4012, 4013, 4014}

StateCallback = Callable[[str, ConnState], Awaitable[None] | None]


class GatewayConnection:
    """One long-lived gateway socket for one account."""

    def __init__(
        self,
        account_id: str,
        token: str,
        status: str | None = None,
        custom_status: CustomStatus | None = None,
        on_state: StateCallback | None = None,
    ):
        self.account_id = account_id
        self.token = token
        # Configured overrides. None means "not configured" -> preserve whatever the
        # account already has (e.g. a custom status set from the phone).
        self.status = status
        self.custom_status = custom_status
        self._on_state = on_state

        # Existing presence captured from READY (what the account currently shows).
        self._ready_status: str | None = None
        self._ready_custom: CustomStatus | None = None

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._seq: int | None = None
        self._session_id: str | None = None
        self._resume_url: str | None = None
        self._heartbeat_interval: float = 41.25
        self._last_ack = True
        self._closed = False
        self._state = ConnState.OFFLINE
        self._run_task: asyncio.Task | None = None
        self._hb_task: asyncio.Task | None = None

    # ---- public API ------------------------------------------------------

    def start(self) -> None:
        """Launch the connection loop as a background task."""
        if self._run_task is None:
            self._closed = False
            self._run_task = asyncio.create_task(self._run(), name=f"gw-{self.account_id}")

    async def stop(self) -> None:
        """Permanently close the connection."""
        self._closed = True
        self._cancel_heartbeat()
        if self._ws is not None:
            await self._ws.close(code=1000)
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
            self._run_task = None
        await self._set_state(ConnState.OFFLINE)

    @property
    def state(self) -> ConnState:
        return self._state

    async def update_presence(
        self, status: str | None = None, custom: CustomStatus | None = None
    ) -> None:
        """Push a live presence change (op 3). Also becomes the default for reconnects."""
        if status is not None:
            self.status = status
        if custom is not None:
            self.custom_status = custom
        if self._ws is not None and self._state is ConnState.ONLINE:
            await self._send(self._presence_payload_op3())

    # ---- presence resolution --------------------------------------------

    def _capture_ready_presence(self, d: dict) -> None:
        """Read the account's current presence from READY (dot + custom status text).

        Prefers the aggregate `sessions` entry (`session_id == "all"`), else any session
        carrying a type-4 (custom status) activity. Falls back to user_settings for the
        custom text. Stored so we can preserve fields the user did not configure.
        """
        status: str | None = None
        custom: CustomStatus | None = None
        sessions = d.get("sessions") or []
        chosen = next((s for s in sessions if s.get("session_id") == "all"), None)
        if chosen is None:
            chosen = next(
                (s for s in sessions
                 if any(a.get("type") == 4 for a in (s.get("activities") or []))),
                None,
            )
        if chosen is not None:
            status = chosen.get("status")
            for a in chosen.get("activities") or []:
                if a.get("type") == 4:
                    custom = CustomStatus.from_activity(a)
                    break
        if custom is None:
            settings = d.get("user_settings")
            cs = settings.get("custom_status") if isinstance(settings, dict) else None
            custom = CustomStatus.from_settings(cs)
        self._ready_status = status
        self._ready_custom = custom

    async def _apply_presence_after_ready(self) -> None:
        """Send one op-3 that merges configured overrides with the account's existing
        presence. Sends nothing when there is nothing to enforce or preserve."""
        if self.status is None and self.custom_status is None \
                and self._ready_status is None and self._ready_custom is None:
            return  # nothing configured and nothing to preserve: leave session default
        if self._ws is not None and self._state is ConnState.ONLINE:
            await self._send(self._presence_payload_op3())

    def _effective_status(self) -> str:
        return self.status or self._ready_status or "online"

    def _effective_custom(self) -> CustomStatus | None:
        return self.custom_status if self.custom_status is not None else self._ready_custom

    # ---- connection loop -------------------------------------------------

    async def _run(self) -> None:
        backoff = 1.0
        while not self._closed:
            try:
                await self._set_state(ConnState.CONNECTING)
                await self._connect_once()
                backoff = 1.0  # clean exit (server RECONNECT) -> reconnect promptly
            except _FatalGateway:
                await self._set_state(ConnState.DEAD)
                return
            except Exception:
                # Network hiccup, zombie, or unexpected close: back off and retry.
                await self._set_state(ConnState.CONNECTING)
            finally:
                self._cancel_heartbeat()
                self._ws = None

            if self._closed:
                break
            await asyncio.sleep(backoff + random.uniform(0, 1.0))
            backoff = min(backoff * 2, 60.0)

        await self._set_state(ConnState.OFFLINE)

    async def _connect_once(self) -> None:
        url = self._resume_url or GATEWAY_URL
        async with websockets.connect(
            url, user_agent_header=_CLIENT_UA, max_size=None, ping_interval=None
        ) as ws:
            self._ws = ws

            hello = json.loads(await ws.recv())
            if hello.get("op") != 10:
                raise RuntimeError("Expected HELLO")
            self._heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000.0
            self._last_ack = True
            self._start_heartbeat()

            if self._session_id and self._seq is not None:
                await self._send(self._resume_payload())
            else:
                await self._send(self._identify_payload())

            async for raw in ws:
                await self._on_message(json.loads(raw))
                if self._closed:
                    await ws.close(1000)
                    return

        # Loop ended: inspect close code for fatal auth failures.
        if self._ws is not None and self._ws.close_code in _FATAL_CLOSE_CODES:
            raise _FatalGateway()

    async def _on_message(self, msg: dict) -> None:
        op = msg.get("op")
        if msg.get("s") is not None:
            self._seq = msg["s"]

        if op == 0:  # DISPATCH
            t = msg.get("t")
            if t == "READY":
                d = msg["d"]
                self._session_id = d.get("session_id")
                resume_url = d.get("resume_gateway_url")
                if resume_url:
                    self._resume_url = f"{resume_url}/?v=9&encoding=json"
                self._capture_ready_presence(d)
                await self._set_state(ConnState.ONLINE)
                await self._apply_presence_after_ready()
            elif t == "RESUMED":
                await self._set_state(ConnState.ONLINE)
        elif op == 1:  # server-requested heartbeat
            await self._send({"op": 1, "d": self._seq})
        elif op == 7:  # RECONNECT
            await self._safe_close(4000)
        elif op == 9:  # INVALID SESSION
            resumable = bool(msg.get("d"))
            if not resumable:
                self._session_id = None
                self._seq = None
                self._resume_url = None
            await asyncio.sleep(random.uniform(1.0, 5.0))
            await self._safe_close(4000)
        elif op == 11:  # HEARTBEAT ACK
            self._last_ack = True

    # ---- heartbeat -------------------------------------------------------

    def _start_heartbeat(self) -> None:
        self._cancel_heartbeat()
        self._hb_task = asyncio.create_task(self._heartbeat_loop())

    def _cancel_heartbeat(self) -> None:
        if self._hb_task is not None:
            self._hb_task.cancel()
            self._hb_task = None

    async def _heartbeat_loop(self) -> None:
        # Jitter the first beat per Discord's guidance.
        await asyncio.sleep(self._heartbeat_interval * random.random())
        while not self._closed and self._ws is not None:
            if not self._last_ack:
                # Zombie connection: no ACK since last beat -> force reconnect.
                await self._safe_close(4000)
                return
            self._last_ack = False
            try:
                await self._send({"op": 1, "d": self._seq})
            except Exception:
                return
            await asyncio.sleep(self._heartbeat_interval)

    # ---- payloads --------------------------------------------------------

    def _identify_payload(self) -> dict:
        return {
            "op": 2,
            "d": {
                "token": self.token,
                "capabilities": 16381,
                "properties": {
                    "os": "Linux",
                    "browser": "Chrome",
                    "device": "",
                    "browser_user_agent": _CLIENT_UA,
                    "browser_version": "124.0.0.0",
                    "os_version": "",
                    "referrer": "",
                    "referring_domain": "",
                    "release_channel": "stable",
                    "client_build_number": 300000,
                },
                # No presence here on purpose: a fresh session is online by default and
                # the account's existing custom status stays intact. We read what the
                # account currently shows from READY and (re)apply via op 3, so we never
                # blank a phone-set custom status. See _apply_presence_after_ready.
                "compress": False,
            },
        }

    def _resume_payload(self) -> dict:
        return {
            "op": 6,
            "d": {
                "token": self.token,
                "session_id": self._session_id,
                "seq": self._seq,
            },
        }

    def _presence_payload_op3(self) -> dict:
        return {"op": 3, "d": self._presence_body()}

    def _presence_body(self) -> dict:
        custom = self._effective_custom()
        activities = []
        if custom is not None and not custom.is_empty:
            activity = {
                "type": 4,  # custom status
                "name": "Custom Status",
                "state": custom.text or None,
            }
            emoji = custom.activity_emoji()
            if emoji:
                activity["emoji"] = emoji
            activities.append(activity)
        return {
            "status": self._effective_status(),
            "since": 0,
            "activities": activities,
            "afk": False,
        }

    # ---- helpers ---------------------------------------------------------

    async def _send(self, payload: dict) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(payload))

    async def _safe_close(self, code: int) -> None:
        if self._ws is not None:
            try:
                await self._ws.close(code)
            except Exception:
                pass

    async def _set_state(self, state: ConnState) -> None:
        if state == self._state:
            return
        self._state = state
        if self._on_state is not None:
            res = self._on_state(self.account_id, state)
            if asyncio.iscoroutine(res):
                await res


class _FatalGateway(Exception):
    """Raised on a non-recoverable close code (bad token)."""
