"""Кабинеты Bybit (бриф, этап 3): добавить с проверкой ключа, перепроверить,
остановить, удалить. Всё — только с включённой 2FA.

Ключ и секрет принимаются один раз, проверяются у Bybit (только чтение) и
сохраняются шифрованно. Наружу — никогда: в ответах только последние 4
символа ключа."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import bybit, crypto
from app.auth import Current, Db, require_2fa, require_login
from app.models import ExchangeAccount
from app.ratelimit import enforce

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

KEY_PURPOSE = "account.api_key"
SECRET_PURPOSE = "account.api_secret"  # noqa: S105 — метка aad, не секрет
MAX_ACCOUNTS = 10

Viewer = Annotated[Current, Depends(require_login)]
Owner2FA = Annotated[Current, Depends(require_2fa)]


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    mode: Literal["demo", "real"] = "demo"
    api_key: str = Field(min_length=10, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    api_secret: str = Field(min_length=10, max_length=128, pattern=r"^[A-Za-z0-9]+$")


class StopIn(BaseModel):
    stopped: bool


def _view(a: ExchangeAccount) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "mode": a.mode,
        "key_tail": a.key_tail,
        "permissions": a.permissions,
        "ips": a.ips,
        "warnings": a.warnings,
        "status": a.status,
        "status_detail": a.status_detail,
        "equity_usd": a.equity_usd,
        "stopped": a.stopped,
        "checked_at": a.checked_at.isoformat() if a.checked_at else None,
        "created_at": a.created_at.isoformat(),
    }


def keys_of(a: ExchangeAccount) -> tuple[str, str]:
    """Ключ и секрет кабинета — для движка и перепроверки, не для ответов."""
    return (
        crypto.decrypt(a.api_key_enc, KEY_PURPOSE).decode(),
        crypto.decrypt(a.api_secret_enc, SECRET_PURPOSE).decode(),
    )


async def _own(db, cur: Current, account_id: uuid.UUID) -> ExchangeAccount:
    a = await db.get(ExchangeAccount, account_id)
    if a is None or a.user_id != cur.user.id:
        raise HTTPException(404, "Нет такого кабинета")
    return a


def _problem(detail: list[str] | str, warnings: list[str] | None = None) -> HTTPException:
    problems = [detail] if isinstance(detail, str) else detail
    return HTTPException(400, {"problems": problems, "warnings": warnings or []})


@router.get("")
async def list_accounts(cur: Viewer, db: Db) -> list[dict]:
    rows = await db.scalars(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == cur.user.id)
        .order_by(ExchangeAccount.created_at)
    )
    return [_view(a) for a in rows]


@router.post("", status_code=201)
async def add_account(body: AccountIn, cur: Owner2FA, request: Request, db: Db) -> dict:
    await enforce(f"accounts:add:{cur.user.id}", 10, 3600)
    count = await db.scalar(
        select(func.count())
        .select_from(ExchangeAccount)
        .where(ExchangeAccount.user_id == cur.user.id)
    )
    if (count or 0) >= MAX_ACCOUNTS:
        raise _problem(f"Не больше {MAX_ACCOUNTS} кабинетов.")
    try:
        chk = await bybit.check_key(body.mode, body.api_key, body.api_secret)
    except bybit.BybitError as e:
        raise _problem(str(e)) from None
    if not chk.ok:
        raise _problem(chk.problems, chk.warnings)
    eq = await bybit.equity(body.mode, body.api_key, body.api_secret)
    a = ExchangeAccount(
        user_id=cur.user.id,
        name=body.name.strip(),
        mode=body.mode,
        api_key_enc=crypto.encrypt(body.api_key.encode(), KEY_PURPOSE),
        api_secret_enc=crypto.encrypt(body.api_secret.encode(), SECRET_PURPOSE),
        key_tail=body.api_key[-4:],
        permissions=chk.permissions,
        ips=chk.ips,
        warnings=chk.warnings,
        status="ok",
        equity_usd=eq,
        checked_at=datetime.now(UTC),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return _view(a)


@router.post("/{account_id}/recheck")
async def recheck(account_id: uuid.UUID, cur: Owner2FA, db: Db) -> dict:
    await enforce(f"accounts:recheck:{cur.user.id}", 30, 3600)
    a = await _own(db, cur, account_id)
    key, secret = keys_of(a)
    try:
        chk = await bybit.check_key(a.mode, key, secret)  # type: ignore[arg-type]
        a.permissions, a.ips, a.warnings = chk.permissions, chk.ips, chk.warnings
        a.status = "ok" if chk.ok else "error"
        a.status_detail = None if chk.ok else " ".join(chk.problems)[:255]
        if chk.ok:
            a.equity_usd = await bybit.equity(a.mode, key, secret)  # type: ignore[arg-type]
    except bybit.BybitError as e:
        a.status, a.status_detail = "error", str(e)[:255]
    a.checked_at = datetime.now(UTC)
    await db.commit()
    return _view(a)


@router.post("/{account_id}/stop")
async def stop(account_id: uuid.UUID, body: StopIn, cur: Owner2FA, db: Db) -> dict:
    """Аварийная остановка кабинета (и снятие её)."""
    a = await _own(db, cur, account_id)
    a.stopped = body.stopped
    await db.commit()
    return _view(a)


@router.delete("/{account_id}")
async def delete(account_id: uuid.UUID, cur: Owner2FA, db: Db) -> dict:
    a = await _own(db, cur, account_id)
    await db.delete(a)
    await db.commit()
    return {"ok": True}
