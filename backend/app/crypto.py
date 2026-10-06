"""Шифрование секретов в БД и работа с токенами.

- AES-256-GCM с мастер-ключом из .env (MASTER_KEY, base64 32 байта): секреты
  2FA, позже — ключи Bybit. Формат: b"v1" + nonce(12) + шифротекст+тег.
  Связка с назначением (aad), чтобы шифротекст одного поля нельзя было
  подложить в другое.
- Токены (сессии, письма) хранятся только хешем SHA-256: утечка базы не даёт
  войти.
"""

import base64
import hashlib
import os
import secrets
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_VERSION = b"v1"


@lru_cache
def _aes() -> AESGCM:
    key = get_settings().master_key
    if key is None:
        raise RuntimeError("MASTER_KEY не задан")
    raw = base64.b64decode(key.get_secret_value())
    if len(raw) != 32:
        raise RuntimeError("MASTER_KEY должен быть 32 байта в base64")
    return AESGCM(raw)


def encrypt(plain: bytes, purpose: str) -> bytes:
    nonce = os.urandom(12)
    return _VERSION + nonce + _aes().encrypt(nonce, plain, purpose.encode())


def decrypt(blob: bytes, purpose: str) -> bytes:
    if blob[:2] != _VERSION:
        raise ValueError("неизвестная версия шифротекста")
    return _aes().decrypt(blob[2:14], blob[14:], purpose.encode())


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
