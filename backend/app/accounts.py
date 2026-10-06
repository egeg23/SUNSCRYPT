"""Кабинеты Bybit (бриф, этапы 3 и 5).

Кабинет — до двух ключей (демо и реальный) и один активный счёт, на котором
идёт торговля. Ключ принимается один раз, проверяется у Bybit (только
чтение) и хранится шифрованно; наружу — только последние 4 символа.

Переход на реальный счёт (этап 5): только при включённой владельцем
реальной торговле, с повторным кодом 2FA, подтверждением рисков, лимитом
депозита и дневного убытка. Движок сначала закрывает позиции на прежнем
счёте и только потом запускается на новом — двойных позиций нет.
Всё, что меняет кабинет, — только с включённой 2FA."""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app import bybit, crypto, safety
from app.auth import Current, Db, check_totp, require_2fa, require_login
from app.cache import redis
from app.db import read_flags
from app.models import AccountKey, EngineEvent, EquitySnapshot, ExchangeAccount, Trade
from app.ratelimit import enforce

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["accounts"])

KEY_PURPOSE = "account.api_key"
SECRET_PURPOSE = "account.api_secret"  # noqa: S105 — метка aad, не секрет
MAX_ACCOUNTS = 10
Mode = Literal["demo", "real"]
MODE_RU = {"demo": "демо", "real": "реальный"}

Viewer = Annotated[Current, Depends(require_login)]
Owner2FA = Annotated[Current, Depends(require_2fa)]

# Пробелы и невидимые символы, которые телефон добавляет при копировании.
_INVISIBLE = re.compile(r"[\s\u00ad\u200b-\u200f\u2028-\u202f\u2060-\u2064\ufeff]")


class KeyIn(BaseModel):
    mode: Mode = "demo"
    api_key: str = Field(min_length=10, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    api_secret: str = Field(min_length=10, max_length=128, pattern=r"^[A-Za-z0-9]+$")

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def _clean(cls, v: object) -> object:
        return _INVISIBLE.sub("", v) if isinstance(v, str) else v


class AccountIn(KeyIn):
    name: str = Field(min_length=1, max_length=60)


class StopIn(BaseModel):
    stopped: bool


class SettingsIn(BaseModel):
    trading_enabled: bool | None = None
    leverage: float | None = Field(default=None, gt=0, le=safety.MAX_LEVERAGE)
    capital_usd: float | None = Field(default=None, ge=50, le=10_000_000)
    daily_loss_pct: float | None = Field(default=None, ge=0.5, le=50)


class ModeIn(BaseModel):
    mode: Mode
    # Для реального счёта — обязательно:
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    confirm_risk: bool = False
    capital_usd: float | None = Field(default=None, ge=50, le=10_000_000)
    daily_loss_pct: float | None = Field(default=None, ge=0.5, le=20)


# ── вспомогательное ────────────────────────────────────────────────────────
async def keys_map(db, account_id) -> dict[str, AccountKey]:
    rows = await db.scalars(select(AccountKey).where(AccountKey.account_id == account_id))
    return {k.mode: k for k in rows}


def secrets_of(k: AccountKey) -> tuple[str, str]:
    """Ключ и секрет — для движка и перепроверки, не для ответов."""
    return (
        crypto.decrypt(k.api_key_enc, KEY_PURPOSE).decode(),
        crypto.decrypt(k.api_secret_enc, SECRET_PURPOSE).decode(),
    )


async def active_secrets(db, a: ExchangeAccount) -> tuple[str, str]:
    k = (await keys_map(db, a.id)).get(a.mode)
    if k is None:
        raise ValueError("нет ключа для активного счёта")
    return secrets_of(k)


def _key_view(k: AccountKey | None) -> dict | None:
    if k is None:
        return None
    return {
        "key_tail": k.key_tail,
        "permissions": k.permissions,
        "ips": k.ips,
        "warnings": k.warnings,
        "status": k.status,
        "status_detail": k.status_detail,
        "equity_usd": k.equity_usd,
        "checked_at": k.checked_at.isoformat() if k.checked_at else None,
    }


def _sync_active(a: ExchangeAccount, keys: dict[str, AccountKey]) -> None:
    k = keys.get(a.mode)
    a.status = k.status if k else "nokey"
    a.equity_usd = k.equity_usd if k else None


def _view(a: ExchangeAccount, keys: dict[str, AccountKey]) -> dict:
    active = keys.get(a.mode)
    return {
        "id": str(a.id),
        "name": a.name,
        "mode": a.mode,
        "status": a.status,
        "equity_usd": a.equity_usd,
        "stopped": a.stopped,
        "trading_enabled": a.trading_enabled,
        "leverage": a.leverage,
        "capital_usd": a.capital_usd,
        "daily_loss_pct": a.daily_loss_pct,
        "keys": {m: _key_view(keys.get(m)) for m in ("demo", "real")},
        # Для совместимости с карточкой: данные активного ключа.
        "key_tail": active.key_tail if active else None,
        "ips": active.ips if active else [],
        "warnings": active.warnings if active else [],
        "status_detail": active.status_detail if active else "Нет ключа для этого счёта",
        "checked_at": active.checked_at.isoformat() if active and active.checked_at else None,
    }


async def _own(db, cur: Current, account_id: uuid.UUID) -> ExchangeAccount:
    a = await db.get(ExchangeAccount, account_id)
    if a is None or a.user_id != cur.user.id:
        raise HTTPException(404, "Нет такого кабинета")
    return a


def _problem(detail: list[str] | str, warnings: list[str] | None = None) -> HTTPException:
    problems = [detail] if isinstance(detail, str) else detail
    return HTTPException(400, {"problems": problems, "warnings": warnings or []})


async def _checked_key(body: KeyIn) -> tuple[bybit.KeyCheck, float | None]:
    try:
        chk = await bybit.check_key(body.mode, body.api_key, body.api_secret)
    except bybit.BybitError as e:
        raise _problem(str(e)) from None
    if not chk.ok:
        raise _problem(chk.problems, chk.warnings)
    return chk, await bybit.equity(body.mode, body.api_key, body.api_secret)


def _fill_key(k: AccountKey, body: KeyIn, chk: bybit.KeyCheck, eq: float | None) -> None:
    k.api_key_enc = crypto.encrypt(body.api_key.encode(), KEY_PURPOSE)
    k.api_secret_enc = crypto.encrypt(body.api_secret.encode(), SECRET_PURPOSE)
    k.key_tail = body.api_key[-4:]
    k.permissions, k.ips, k.warnings = chk.permissions, chk.ips, chk.warnings
    k.status, k.status_detail, k.equity_usd = "ok", None, eq
    k.checked_at = datetime.now(UTC)


async def _event(db, a: ExchangeAccount, kind: str, message: str) -> None:
    db.add(EngineEvent(account_id=a.id, kind=kind, message=message))


async def _redis_set(key: str, value: str) -> None:
    try:
        await redis.set(key, value)
    except Exception:  # Redis недоступен — диспетчер подхватит флаг из базы
        log.warning("Redis недоступен")


# ── кабинеты ───────────────────────────────────────────────────────────────
@router.get("")
async def list_accounts(cur: Viewer, db: Db) -> list[dict]:
    rows = list(
        await db.scalars(
            select(ExchangeAccount)
            .where(ExchangeAccount.user_id == cur.user.id)
            .order_by(ExchangeAccount.created_at)
        )
    )
    return [_view(a, await keys_map(db, a.id)) for a in rows]


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
    chk, eq = await _checked_key(body)
    a = ExchangeAccount(user_id=cur.user.id, name=body.name.strip(), mode=body.mode)
    db.add(a)
    await db.flush()
    k = AccountKey(account_id=a.id, mode=body.mode)
    _fill_key(k, body, chk, eq)
    db.add(k)
    _sync_active(a, {body.mode: k})
    await db.commit()
    return _view(a, {body.mode: k})


@router.post("/{account_id}/keys")
async def put_key(account_id: uuid.UUID, body: KeyIn, cur: Owner2FA, db: Db) -> dict:
    """Подключить или заменить ключ демо или реального счёта."""
    await enforce(f"accounts:add:{cur.user.id}", 10, 3600)
    a = await _own(db, cur, account_id)
    chk, eq = await _checked_key(body)
    keys = await keys_map(db, a.id)
    k = keys.get(body.mode) or AccountKey(account_id=a.id, mode=body.mode)
    _fill_key(k, body, chk, eq)
    if body.mode not in keys:
        db.add(k)
        keys[body.mode] = k
    _sync_active(a, keys)
    await _event(db, a, "key", f"Ключ счёта «{MODE_RU[body.mode]}» подключён (••••{k.key_tail})")
    await db.commit()
    return _view(a, keys)


@router.post("/{account_id}/recheck")
async def recheck(account_id: uuid.UUID, cur: Owner2FA, db: Db) -> dict:
    await enforce(f"accounts:recheck:{cur.user.id}", 30, 3600)
    a = await _own(db, cur, account_id)
    keys = await keys_map(db, a.id)
    for mode, k in keys.items():
        key, secret = secrets_of(k)
        try:
            chk = await bybit.check_key(mode, key, secret)  # type: ignore[arg-type]
            k.permissions, k.ips, k.warnings = chk.permissions, chk.ips, chk.warnings
            k.status = "ok" if chk.ok else "error"
            k.status_detail = None if chk.ok else " ".join(chk.problems)[:255]
            if chk.ok:
                k.equity_usd = await bybit.equity(mode, key, secret)  # type: ignore[arg-type]
        except bybit.BybitError as e:
            k.status, k.status_detail = "error", str(e)[:255]
        k.checked_at = datetime.now(UTC)
    _sync_active(a, keys)
    await db.commit()
    return _view(a, keys)


@router.post("/{account_id}/stop")
async def stop(account_id: uuid.UUID, body: StopIn, cur: Owner2FA, db: Db) -> dict:
    """Аварийная остановка кабинета (и снятие её). Движок узнаёт сразу через
    Redis: закрывает позиции и отменяет ордера."""
    a = await _own(db, cur, account_id)
    a.stopped = body.stopped
    await _event(
        db,
        a,
        "stop" if body.stopped else "resume",
        "Аварийная остановка" if body.stopped else "Остановка снята",
    )
    await db.commit()
    await _redis_set(f"stop:acct:{a.id}", "1" if body.stopped else "0")
    return _view(a, await keys_map(db, a.id))


async def _real_allowed(db) -> bool:
    flags = await read_flags(db)
    return safety.real_mode_allowed(
        flags.get("real_trading_enabled", False), flags.get("global_stop", False)
    )


REAL_OFF = "Торговля на реальном счёте пока выключена владельцем сервиса. Доступен демо-счёт."


@router.patch("/{account_id}/settings")
async def settings(account_id: uuid.UUID, body: SettingsIn, cur: Owner2FA, db: Db) -> dict:
    """Торговля вкл/выкл, плечо (≤ 2×), капитал под стратегию, дневной лимит."""
    a = await _own(db, cur, account_id)
    if body.trading_enabled:
        if a.status != "ok":
            raise _problem("Сначала исправьте ключ: кабинет с ошибкой торговать не может.")
        if a.mode == "real" and not await _real_allowed(db):
            raise _problem(REAL_OFF)
    for field in ("trading_enabled", "leverage", "capital_usd", "daily_loss_pct"):
        v = getattr(body, field)
        if v is not None:
            setattr(a, field, v)
    if body.trading_enabled is not None:
        await _event(
            db, a, "trading", "Торговля включена" if body.trading_enabled else "Торговля выключена"
        )
    await db.commit()
    return _view(a, await keys_map(db, a.id))


@router.post("/{account_id}/mode")
async def switch_mode(account_id: uuid.UUID, body: ModeIn, cur: Owner2FA, db: Db) -> dict:
    """Переключатель «Демо ↔ Реальный» (бриф, этап 5)."""
    a = await _own(db, cur, account_id)
    keys = await keys_map(db, a.id)
    if body.mode == a.mode:
        return _view(a, keys)
    k = keys.get(body.mode)
    if k is None or k.status != "ok":
        raise _problem(f"Сначала подключите исправный ключ счёта «{MODE_RU[body.mode]}».")
    if body.mode == "real":
        await enforce(f"2fa:user:{cur.user.id}", 8, 900)
        if not await _real_allowed(db):
            raise _problem(REAL_OFF)
        if not body.confirm_risk:
            raise _problem("Подтвердите, что понимаете риски торговли на реальные деньги.")
        if body.capital_usd is None or body.daily_loss_pct is None:
            raise _problem("Укажите лимит депозита и дневной лимит убытка.")
        if k.equity_usd is not None and body.capital_usd > k.equity_usd:
            raise _problem(f"Лимит депозита больше баланса счёта ({k.equity_usd:,.2f} USD).")
        if not body.code or not check_totp(cur.user, body.code):
            await db.commit()  # шаг TOTP мог сдвинуться
            raise _problem("Неверный код 2FA. Для реального счёта нужен свежий код.")
        a.capital_usd, a.daily_loss_pct = body.capital_usd, body.daily_loss_pct
    prev = a.mode
    a.mode = body.mode
    _sync_active(a, keys)
    await _event(
        db,
        a,
        "mode",
        f"Счёт: {MODE_RU[prev]} → {MODE_RU[body.mode]}"
        + (
            ". Движок закроет позиции на прежнем счёте, потом начнёт на новом"
            if a.trading_enabled
            else ""
        ),
    )
    await db.commit()
    return _view(a, keys)


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


async def ensure_owner_demo(db) -> None:
    """Демо-кабинет владельца из секретов SUNSCRYPT_BYBIT_DEMO_API_* (просьба
    владельца «подключи сам»). Создаётся один раз, с торговлей на демо;
    ключ проверяется у Bybit теми же правилами, что ключи пользователей."""
    from app.config import get_settings
    from app.models import User

    s = get_settings()
    if not (s.owner_email and s.bybit_demo_api_key and s.bybit_demo_api_secret):
        return
    owner = await db.scalar(select(User).where(User.email == s.owner_email.strip().lower()))
    if owner is None:
        return
    body = KeyIn(
        mode="demo",
        api_key=s.bybit_demo_api_key.get_secret_value(),
        api_secret=s.bybit_demo_api_secret.get_secret_value(),
    )
    exists = await db.scalar(
        select(AccountKey.id)
        .join(ExchangeAccount, ExchangeAccount.id == AccountKey.account_id)
        .where(
            ExchangeAccount.user_id == owner.id,
            AccountKey.mode == "demo",
            AccountKey.key_tail == body.api_key[-4:],
        )
    )
    if exists:
        return
    try:
        chk, eq = await _checked_key(body)
    except HTTPException as e:
        log.warning("демо-кабинет владельца не создан: %s", e.detail)
        return
    a = ExchangeAccount(
        user_id=owner.id, name="Демо (ключ владельца)", mode="demo", trading_enabled=True
    )
    db.add(a)
    await db.flush()
    k = AccountKey(account_id=a.id, mode="demo")
    _fill_key(k, body, chk, eq)
    db.add(k)
    _sync_active(a, {"demo": k})
    await _event(
        db, a, "trading", "Демо-кабинет владельца подключён из секретов; торговля включена"
    )
    await db.commit()
    log.info("демо-кабинет владельца подключён, торговля включена")
