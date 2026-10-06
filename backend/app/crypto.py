"""Шифрование секретов в БД и работа с токенами.

- AES-256-GCM с мастер-ключом из .env (MASTER_KEY, base64 32 байта): ключи
  Bybit, секреты 2FA. Связка с назначением (aad), чтобы шифротекст одного
  поля нельзя было подложить в другое.
- Формат v2: b"v2" + id ключа (8 байт) + nonce (12) + шифротекст+тег. По id
  выбирается ключ, поэтому мастер-ключ можно сменить: новый — MASTER_KEY,
  прежний — MASTER_KEY_PREVIOUS; `python -m app.rotate` перешифровывает всё
  новым. Формат v1 (без id, только MASTER_KEY) читается для старых записей.
- Токены (сессии, письма, приглашения) хранятся только хешем SHA-256.
"""

import base64
import hashlib
import os
import secrets
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def _raw(b64: str) -> bytes:
    raw = base64.b64decode(b64)
    if len(raw) != 32:
        raise RuntimeError("мастер-ключ должен быть 32 байта в base64")
    return raw


def _kid(raw: bytes) -> bytes:
    return hashlib.sha256(b"sunscrypt-kid" + raw).digest()[:8]


@lru_cache
def _keys() -> tuple[bytes, dict[bytes, AESGCM]]:
    """(id текущего ключа, {id: шифр}) — текущий и прежний."""
    s = get_settings()
    if s.master_key is None:
        raise RuntimeError("MASTER_KEY не задан")
    cur = _raw(s.master_key.get_secret_value())
    keys = {_kid(cur): AESGCM(cur)}
    if s.master_key_previous:
        prev = _raw(s.master_key_previous.get_secret_value())
        keys[_kid(prev)] = AESGCM(prev)
    return _kid(cur), keys


def encrypt(plain: bytes, purpose: str) -> bytes:
    kid, keys = _keys()
    nonce = os.urandom(12)
    return b"v2" + kid + nonce + keys[kid].encrypt(nonce, plain, purpose.encode())


def decrypt(blob: bytes, purpose: str) -> bytes:
    kid, keys = _keys()
    if blob[:2] == b"v2":
        aes = keys.get(blob[2:10])
        if aes is None:
            raise ValueError("шифротекст сделан неизвестным мастер-ключом")
        return aes.decrypt(blob[10:22], blob[22:], purpose.encode())
    if blob[:2] == b"v1":
        return keys[kid].decrypt(blob[2:14], blob[14:], purpose.encode())
    raise ValueError("неизвестная версия шифротекста")


def is_current(blob: bytes) -> bool:
    """Зашифровано текущим мастер-ключом в актуальном формате."""
    return blob[:2] == b"v2" and blob[2:10] == _keys()[0]


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
