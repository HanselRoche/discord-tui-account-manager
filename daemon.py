"""Headless presence daemon: keep accounts online, no UI.

Meant to run 24/7 under systemd (or tmux). Reads the same encrypted vault as the TUI
and the plain `presence.json` config, opens one gateway connection per account, and
holds them online forever. Logs to stdout for journald.

Passphrase comes from env `DISCORD_VAULT_PASS`, else a one-time getpass prompt.

Run:  DISCORD_VAULT_PASS=... python daemon.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from getpass import getpass

from src import presence_config, vault
from src.models import ConnState
from src.presence_manager import PresenceManager

log = logging.getLogger("daemon")


def _get_passphrase() -> str:
    env = os.environ.get("DISCORD_VAULT_PASS")
    if env:
        return env
    return getpass("Vault passphrase: ")


def _on_state(label: str, state: ConnState) -> None:
    log.info("account %s -> %s", label, state.value)


async def _amain() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    passphrase = _get_passphrase()
    if not vault.verify_passphrase(passphrase):
        log.error("wrong passphrase — aborting")
        return 1

    accounts = vault.load(passphrase)
    if not accounts:
        log.error("vault empty — add tokens with the TUI first")
        return 1
    log.info("vault loaded: %d account(s)", len(accounts))

    presence = PresenceManager(on_state=_on_state)
    await presence.start_all(accounts, presence_for=presence_config.for_label)

    # Wait for SIGINT/SIGTERM, then shut down cleanly.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. non-main thread / some platforms
            pass

    log.info("daemon running — accounts staying online (Ctrl-C to stop)")
    await stop.wait()

    log.info("shutting down — closing gateway connections")
    await presence.stop_all()
    return 0


def run() -> None:
    try:
        raise SystemExit(asyncio.run(_amain()))
    except KeyboardInterrupt:
        raise SystemExit(0)


if __name__ == "__main__":
    run()
