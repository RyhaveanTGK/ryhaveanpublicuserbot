from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import settings


def _derive_key() -> bytes:
    raw = settings.master_key.strip()
    if not raw:
        raise RuntimeError("MASTER_KEY env təyin edilməyib")

    try:
        decoded = base64.urlsafe_b64decode(raw.encode())
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    return hashlib.sha256(raw.encode()).digest()


def encrypt_text(value: str) -> str:
    if value is None:
        value = ""
    aes = AESGCM(_derive_key())
    nonce = os.urandom(12)
    token = nonce + aes.encrypt(nonce, value.encode(), None)
    return base64.urlsafe_b64encode(token).decode()


def decrypt_text(value: str | None) -> str:
    if not value:
        return ""
    aes = AESGCM(_derive_key())
    raw = base64.urlsafe_b64decode(value.encode())
    return aes.decrypt(raw[:12], raw[12:], None).decode()
