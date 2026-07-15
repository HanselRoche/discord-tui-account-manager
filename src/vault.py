"""Encrypted token store.

Tokens live in `data/tokens.enc`, encrypted with Fernet using a key derived from
a user passphrase via PBKDF2-HMAC-SHA256. The random salt sits in `data/tokens.salt`.
The passphrase is never written to disk.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .models import Account

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ENC_PATH = DATA_DIR / "tokens.enc"
SALT_PATH = DATA_DIR / "tokens.salt"

_KDF_ITERATIONS = 200_000


class VaultError(Exception):
    """Raised on decrypt failure (usually wrong passphrase)."""


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _get_salt() -> bytes:
    """Load the salt, creating a fresh random one on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SALT_PATH.exists():
        return SALT_PATH.read_bytes()
    salt = os.urandom(16)
    SALT_PATH.write_bytes(salt)
    return salt


def _fernet(passphrase: str) -> Fernet:
    return Fernet(_derive_key(passphrase, _get_salt()))


def vault_exists() -> bool:
    return ENC_PATH.exists()


def load(passphrase: str) -> list[Account]:
    """Decrypt and return the account list. Empty list if no vault yet."""
    if not ENC_PATH.exists():
        return []
    try:
        raw = _fernet(passphrase).decrypt(ENC_PATH.read_bytes())
    except InvalidToken as exc:
        raise VaultError("Wrong passphrase or corrupted vault.") from exc
    data = json.loads(raw.decode("utf-8"))
    return [Account.from_json(d) for d in data]


def save(accounts: list[Account], passphrase: str) -> None:
    """Encrypt and write the account list."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([a.to_json() for a in accounts]).encode("utf-8")
    token = _fernet(passphrase).encrypt(payload)
    # Write to a temp file then replace, so a crash can't truncate the vault.
    tmp = ENC_PATH.with_suffix(".enc.tmp")
    tmp.write_bytes(token)
    tmp.replace(ENC_PATH)


def verify_passphrase(passphrase: str) -> bool:
    """True if the passphrase decrypts an existing vault (or none exists yet)."""
    if not ENC_PATH.exists():
        return True
    try:
        load(passphrase)
        return True
    except VaultError:
        return False
