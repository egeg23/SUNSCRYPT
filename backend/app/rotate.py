"""Перешифровка секретов текущим мастер-ключом.

Смена мастер-ключа: в /opt/sunscrypt/.env прежний MASTER_KEY переносится в
MASTER_KEY_PREVIOUS, в MASTER_KEY — новый (openssl rand -base64 32); выкатка
запускает `python -m app.rotate`. Когда напишет «перешифровано: 0» —
MASTER_KEY_PREVIOUS можно убрать. Идемпотентно: что уже под текущим ключом,
не трогает."""

import asyncio

from sqlalchemy import select

from app import crypto
from app.accounts import KEY_PURPOSE, SECRET_PURPOSE
from app.auth import TOTP_PURPOSE
from app.db import SessionLocal
from app.models import AccountKey, User


def _re(blob: bytes | None, purpose: str) -> bytes | None:
    if blob is None or crypto.is_current(blob):
        return None
    return crypto.encrypt(crypto.decrypt(blob, purpose), purpose)


async def main() -> int:
    n = 0
    async with SessionLocal() as db:
        for u in await db.scalars(select(User).where(User.totp_secret_enc.is_not(None))):
            if (new := _re(u.totp_secret_enc, TOTP_PURPOSE)) is not None:
                u.totp_secret_enc, n = new, n + 1
        for a in await db.scalars(select(AccountKey)):
            if (new := _re(a.api_key_enc, KEY_PURPOSE)) is not None:
                a.api_key_enc, n = new, n + 1
            if (new := _re(a.api_secret_enc, SECRET_PURPOSE)) is not None:
                a.api_secret_enc, n = new, n + 1
        await db.commit()
    print(f"перешифровано: {n}")
    return n


if __name__ == "__main__":
    asyncio.run(main())
