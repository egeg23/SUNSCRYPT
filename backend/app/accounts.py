"""Кабинеты Bybit (бриф, этап 3): добавить с проверкой ключа, перепроверить,
остановить, удалить. Всё — только с включённой 2FA.

Ключ и секрет принимаются один раз, проверяются у Bybit (только чтение) и
сохраняются шифрованно. Наружу — никогда: в ответах только последние 4
символа ключа."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import bybit, crypto, safety
from app.auth import Current, Db, require_2fa, require_login
from app.cache import redis
from app.db import read_flags
from app.models import EngineEvent, EquitySnapshot, ExchangeAccount, Trade
from app.ratelimit import enforce

log = logging.getLogger(__name__)
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


class SettingsIn(BaseModel):
    trading_enabled: bool | None = None
    leverage: float | None = Field(default=None, gt=0, le=safety.MAX_LEVERAGE)
    capital_usd: float | None = Field(default=None, ge=50, le=10_000_000)
    daily_loss_pct: float | None = Field(default=None, ge=0.5, le=50)


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
        "trading_enabled": a.trading_enabled,
        "leverage": a.leverage,
        "capital_usd": a.capital_usd,
        "daily_loss_pct": a.daily_loss_pct,
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
    """Аварийная остановка кабинета (и снятие её). Движок узнаёт сразу через
    Redis: закрывает позиции и отменяет ордера."""
    a = await _own(db, cur, account_id)
    a.stopped = body.stopped
    db.add(
        EngineEvent(
            account_id=a.id,
            kind="stop" if body.stopped else "resume",
            message="Аварийная остановка" if body.stopped else "Остановка снята",
        )
    )
    await db.commit()
    try:
        await redis.set(f"stop:acct:{a.id}", "1" if body.stopped else "0")
    except Exception:  # Redis недоступен — диспетчер подхватит флаг из базы
        log.warning("Redis недоступен")
    return _view(a)


@router.patch("/{account_id}/settings")
async def settings(account_id: uuid.UUID, body: SettingsIn, cur: Owner2FA, db: Db) -> dict:
    """Торговля вкл/выкл, плечо (≤ 2×), капитал под стратегию, дневной лимит."""
    a = await _own(db, cur, account_id)
    if body.trading_enabled:
        if a.status != "ok":
            raise _problem("Сначала исправьте ключ: кабинет с ошибкой торговать не может.")
        if a.mode == "real":
            flags = await read_flags(db)
            if not safety.real_mode_allowed(
                flags.get("real_trading_enabled", False), flags.get("global_stop", False)
            ):
                raise _problem(
                    "Торговля на реальном счёте пока выключена владельцем сервиса. "
                    "Доступен демо-счёт."
                )
    for field in ("trading_enabled", "leverage", "capital_usd", "daily_loss_pct"):
        v = getattr(body, field)
        if v is not None:
            setattr(a, field, v)
    if body.trading_enabled is not None:
        db.add(
            EngineEvent(
                account_id=a.id,
                kind="trading",
                message="Торговля включена" if body.trading_enabled else "Торговля выключена",
            )
        )
    await db.commit()
    return _view(a)


@router.get("/{account_id}/engine")
async def engine_state(account_id: uuid.UUID, cur: Viewer, db: Db) -> dict:
    """Что делает движок по кабинету: процесс, позиции, сделки, события."""
    a = await _own(db, cur, account_id)
    hb = None
    recon = None
    try:
        raw = await redis.get(f"hb:acct:{a.id}")
        hb = json.loads(raw) if raw else None
        raw = await redis.get(f"recon:{a.id}")
        recon = json.loads(raw) if raw else None
    except Exception:  # Redis недоступен — диспетчер подхватит флаг из базы
        log.warning("Redis недоступен")
    trades = await db.scalars(
        select(Trade).where(Trade.account_id == a.id).order_by(Trade.ts.desc()).limit(50)
    )
    events = await db.scalars(
        select(EngineEvent)
        .where(EngineEvent.account_id == a.id)
        .order_by(EngineEvent.ts.desc())
        .limit(30)
    )
    eq = await db.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.account_id == a.id)
        .order_by(EquitySnapshot.ts.desc())
        .limit(1)
    )
    last_eq = eq.first()
    return {
        "heartbeat": hb,
        "reconcile": recon,
        "equity": {"ts": last_eq.ts.isoformat(), "usd": last_eq.equity_usd} if last_eq else None,
        "trades": [
            {
                "ts": t.ts.isoformat(),
                "sym": t.sym,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "fee": t.fee,
                "fee_ccy": t.fee_ccy,
                "liquidity": t.liquidity,
                "source": t.source,
            }
            for t in trades
        ],
        "events": [{"ts": e.ts.isoformat(), "kind": e.kind, "message": e.message} for e in events],
    }


@router.delete("/{account_id}")
async def delete(account_id: uuid.UUID, cur: Owner2FA, db: Db) -> dict:
    a = await _own(db, cur, account_id)
    await db.delete(a)
    await db.commit()
    return {"ok": True}
