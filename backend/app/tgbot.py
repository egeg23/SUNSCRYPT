"""Telegram-бот SUNSCRYPT (бриф, этап 9).

Привязка: на сайте (Профиль → Telegram) — одноразовый код на 10 минут,
боту — /start <код>. Дальше бот:
- присылает каждую сделку кабинетов пользователя (Redis pub/sub live:*,
  в момент исполнения — быстрее 5 с);
- тревоги наблюдения (engine_events kind=alarm) — владельцу кабинета, общие —
  владельцу сервиса;
- дневной отчёт в 00:05 UTC;
- команды /status, /report, /stop (аварийная остановка своих кабинетов),
  владельцу — /invite (приглашение нового человека), /help.

Без токена (секрет SUNSCRYPT_TELEGRAM_TOKEN) служба ждёт и ничего не шлёт.

    python -m app.tgbot
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app import cache
from app.auth import Current, Db, new_invite, require_2fa, require_login
from app.db import SessionLocal
from app.models import EngineEvent, ExchangeAccount, User

log = logging.getLogger("tgbot")

BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "SUNSCRYPT_tradebot")
LINK_TTL_S = 600
MODE_RU = {"demo": "демо", "real": "реальный"}

HELP = (
    "SUNSCRYPT — уведомления о сделках, тревоги, дневной отчёт.\n\n"
    "/status — кабинеты: позиции, результат за сегодня, остановки\n"
    "/report — отчёт за сегодня\n"
    "/stop — аварийная остановка торговли во всех ваших кабинетах\n"
    "/help — справка\n\n"
    "Снять остановку — на сайте, в разделе «Bybit». Прибыль не гарантирована."
)
NOT_LINKED = (
    "Этот чат не привязан. На сайте SUNSCRYPT откройте «Профиль → Telegram», "
    "нажмите «Привязать» и отправьте сюда код: /start <код>."
)


# ── сайт: привязка ──────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/auth/telegram", tags=["telegram"])
TwoFA = Annotated[Current, Depends(require_2fa)]
Viewer = Annotated[Current, Depends(require_login)]


@router.post("/link")
async def link_code(cur: TwoFA) -> dict:
    """Одноразовый код привязки (бот может остановить торговлю — нужна 2FA)."""
    code = secrets.token_hex(4).upper()
    await cache.redis.set(f"tglink:{code}", str(cur.user.id), ex=LINK_TTL_S)
    return {
        "code": code,
        "link": f"https://t.me/{BOT_USERNAME}?start={code}",
        "expires_in": LINK_TTL_S,
    }


@router.delete("")
async def unlink(cur: Viewer, db: Db) -> dict:
    user = await db.get(User, cur.user.id)
    user.telegram_chat_id = None
    await db.commit()
    return {"ok": True}


# ── клиент Telegram ─────────────────────────────────────────────────────────
class TG:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None):
        api = os.environ.get("TELEGRAM_API", "https://api.telegram.org").rstrip("/")
        self.base = f"{api}/bot{token}"
        self.http = httpx.AsyncClient(timeout=40, transport=transport)

    async def call(self, method: str, **params) -> dict:
        r = await self.http.post(f"{self.base}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            # Без токена в тексте: он в адресе, а не в ответе.
            log.warning("telegram %s: %s", method, data.get("description"))
        return data

    async def send(self, chat_id: int, text: str) -> None:
        await self.call("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)


# ── тексты ──────────────────────────────────────────────────────────────────
def _usd(v: float) -> str:
    return f"{v:+,.2f} USD".replace(",", " ").replace("-", "−")


def _trend(v: float) -> str:
    return "📈" if v >= 0 else "📉"


def _money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


def _qty(q: float) -> str:
    return f"{abs(q):,.4f}".rstrip("0").rstrip(".").replace(",", " ")


def _balance(equity: float | None) -> str | None:
    return f"💰 Баланс: {_money(equity)} USDT" if equity is not None else None


def _trades(n: int) -> str:
    tail = (
        "сделка"
        if n % 10 == 1 and n % 100 != 11
        else ("сделки" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "сделок")
    )
    return f"{n} {tail}"


def _what(f: dict) -> str:
    """Что сделка сделала с позицией."""
    before, after, closed = float(f["pos_before"]), float(f["pos_after"]), float(f["closed_qty"])
    side = lambda q: "лонг" if q > 0 else "шорт"  # noqa: E731
    if not closed:
        return f"открыт {side(after)}" if before == 0 else f"добавлено к {side(before)}у"
    if after == 0:
        return f"закрыт {side(before)}"
    if (after > 0) == (before > 0):
        return f"частично закрыт {side(before)}"
    return f"закрыт {side(before)}, открыт {side(after)}"


def fmt_fill(f: dict, name: str, day_open: float | None = None, equity: float | None = None) -> str:
    buy = f.get("side") == "buy"
    fee = float(f.get("fee") or 0)
    mode = MODE_RU.get(f.get("mode", "demo"), f.get("mode"))
    deal = (
        f"{'🔼 Покупка' if buy else '🔽 Продажа'} {f.get('qty')} {f.get('sym')} по {f.get('price')}"
    )
    who = f"🤖 {name} · {mode}"
    if "net" not in f:  # исполнитель старой версии — без результата
        ccy = f.get("fee_ccy") or "USDT"
        return f"🔔 Сделка\n{who}\n\n{deal}\n🧾 Комиссия {fee:.4f} {ccy}"
    net = float(f["net"])
    if float(f["closed_qty"]):
        icon, head = ("🟢", "Прибыль") if net >= 0 else ("🔴", "Убыток")
        lines = [
            f"{icon} {head} {_usd(net)}",
            who,
            "",
            deal,
            f"🔒 {_what(f).capitalize()} (вход {float(f['entry_px']):g})",
            f"💵 Результат {_usd(float(f['pnl']))}",
            f"🧾 Комиссия {_usd(-fee)}",
        ]
    else:
        lines = [
            f"⚪ {_what(f).capitalize()}",
            who,
            "",
            deal,
            f"💵 Объём ≈ {float(f['qty']) * float(f['price']):,.0f} USD".replace(",", " "),
            f"🧾 Комиссия {_usd(-fee)}",
            "⏳ Прибыль или убыток — при закрытии",
        ]
    day_net, day_n = float(f["day_net"]), int(f["day_fills"])
    lines += ["", f"{_trend(day_net)} Итог дня по сделкам: {_usd(day_net)} ({_trades(day_n)})"]
    if day_open is not None:
        lines.append(f"{_trend(day_open)} С открытыми позициями: {_usd(day_open)}")
    if (bal := _balance(equity)) is not None:
        lines.append(bal)
    return "\n".join(lines)


async def _hb(aid) -> dict | None:
    raw = await cache.redis.get(f"hb:acct:{aid}")
    return json.loads(raw) if raw else None


async def _day_total(aid, day: str) -> float | None:
    v = await cache.redis.get(f"daytotal:{aid}:{day}")
    return float(v) if v is not None else None


async def account_lines(a: ExchangeAccount, day: str) -> list[str]:
    """Блок кабинета для /status и отчётов: каждая величина — своей строкой."""
    hb = await _hb(a.id)
    lines = [f"🤖 {a.name} · {MODE_RU.get(a.mode, a.mode)}"]
    if a.stopped:
        lines.append("🛑 Аварийная остановка")
    elif a.trading_enabled:
        lines.append("✅ Торговля включена")
    else:
        lines.append("⏸ Торговля выключена")
    dd = await cache.redis.get(f"ddhalt:{a.id}:{a.mode}")
    if dd:
        lines.append(f"⛔ Стоит: {dd.decode()}")
    elif hb and hb.get("halted"):
        lines.append(f"⛔ Стоит: {hb['halted']}")
    if (bal := _balance(a.equity_usd)) is not None:
        lines.append(bal)
    if hb:
        pos, upnl = hb.get("positions") or {}, hb.get("upnl") or {}
        if pos:
            lines += ["", "📂 Позиции:"]
            for sym, q in pos.items():
                arrow, side = ("🔼", "лонг") if q > 0 else ("🔽", "шорт")
                line = f"{arrow} {sym.removesuffix('USDT')} {side} {_qty(q)}"
                if sym in upnl:
                    u = float(upnl[sym])
                    line += f" · {'🟢' if u >= 0 else '🔴'} {_usd(u)}"
                lines.append(line)
        else:
            lines += ["", "📂 Позиций нет"]
    day_lines = []
    net = await cache.redis.hgetall(f"daynet:{a.id}:{a.mode}:{day}")
    if net:
        n, v = int(net.get(b"n", 0)), float(net.get(b"net", 0))
        day_lines.append(f"{_trend(v)} Итог по сделкам: {_usd(v)} ({_trades(n)})")
    total = await _day_total(a.id, day)
    if total is not None:
        day_lines.append(f"{_trend(total)} С открытыми позициями: {_usd(total)}")
    if day_lines:
        lines += ["", "📅 За сутки (UTC), после комиссий:", *day_lines]
    return lines


async def _accounts(db, user_id) -> list[ExchangeAccount]:
    return list(
        await db.scalars(
            select(ExchangeAccount)
            .where(ExchangeAccount.user_id == user_id)
            .order_by(ExchangeAccount.created_at)
        )
    )


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


# ── команды ─────────────────────────────────────────────────────────────────
async def handle_update(tg: TG, upd: dict) -> None:
    msg = upd.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if not chat or not text.startswith("/"):
        return
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat))
        if cmd == "/start":
            if not arg:
                await tg.send(chat, HELP if user else NOT_LINKED)
                return
            uid = await cache.redis.getdel(f"tglink:{arg.upper()}")
            if not uid:
                await tg.send(chat, "Код не подошёл или устарел. Получите новый на сайте.")
                return
            target = await db.get(User, uuid.UUID(uid.decode()))
            other = await db.scalar(select(User).where(User.telegram_chat_id == chat))
            if other and other.id != target.id:
                other.telegram_chat_id = None  # чат — одному аккаунту
            target.telegram_chat_id = chat
            await db.commit()
            await tg.send(chat, f"Готово: бот привязан к {target.email}.\n\n{HELP}")
            return
        if user is None:
            await tg.send(chat, NOT_LINKED)
            return
        if cmd == "/help":
            await tg.send(chat, HELP)
        elif cmd in ("/status", "/report"):
            accounts = await _accounts(db, user.id)
            if not accounts:
                await tg.send(chat, "Кабинетов Bybit нет — подключите на сайте, раздел «Bybit».")
                return
            now = datetime.now(UTC).strftime("%H:%M")
            head = f"📊 Состояние на {now} UTC" if cmd == "/status" else "📊 Отчёт за сегодня (UTC)"
            lines = [head]
            for a in accounts:
                lines += ["", "━━━━━━━━━━━━", *await account_lines(a, _today())]
            await tg.send(chat, "\n".join(lines))
        elif cmd == "/stop":
            accounts = await _accounts(db, user.id)
            for a in accounts:
                a.stopped = True
                msg = "Аварийная остановка из Telegram"
                db.add(EngineEvent(account_id=a.id, kind="stop", message=msg))
            await db.commit()
            for a in accounts:
                await cache.redis.set(f"stop:acct:{a.id}", "1")
            await tg.send(
                chat,
                f"Аварийная остановка: кабинетов — {len(accounts)}. Движок отменяет ордера и "
                "закрывает позиции. Снять — на сайте, раздел «Bybit».",
            )
        elif cmd == "/invite":
            if not user.is_admin:
                await tg.send(chat, "Только для владельца сервиса.")
                return
            link = await new_invite(db, user, arg[:120] or "из Telegram")
            await db.commit()
            await tg.send(chat, f"Приглашение (одноразовое, 7 дней):\n{link}")
        else:
            await tg.send(chat, "Не знаю такой команды.\n\n" + HELP)


# ── уведомления ─────────────────────────────────────────────────────────────
async def _chat_of_account(db, aid: str) -> tuple[int | None, str]:
    a = await db.get(ExchangeAccount, uuid.UUID(aid))
    if a is None:
        return None, ""
    u = await db.get(User, a.user_id)
    return (u.telegram_chat_id if u else None), a.name


async def notify_fill(tg: TG, channel: str, data: dict) -> None:
    aid = channel.removeprefix("live:")
    async with SessionLocal() as db:
        chat, name = await _chat_of_account(db, aid)
        acc = await db.get(ExchangeAccount, uuid.UUID(aid)) if chat else None
    if chat:
        day = datetime.fromtimestamp(int(data.get("ts") or 0) / 1000 or time.time(), UTC)
        day_open = await _day_total(aid, day.strftime("%Y%m%d"))
        equity = acc.equity_usd if acc is not None else None
        await tg.send(chat, fmt_fill(data, name, day_open, equity))
        if data.get("ts"):  # от исполнения на бирже до отправки в Telegram (бриф: < 5 с)
            log.info(
                "сделка %s → Telegram за %.1f с",
                data.get("sym"),
                time.time() - int(data["ts"]) / 1000,
            )


async def fills_loop(tg: TG) -> None:
    ps = cache.redis.pubsub()
    await ps.psubscribe("live:*")
    async for m in ps.listen():
        if m.get("type") != "pmessage":
            continue
        try:
            data = json.loads(m["data"])
            if data.get("type") == "fill":
                await notify_fill(tg, m["channel"].decode(), data)
        except Exception:
            log.exception("уведомление о сделке")


async def send_alarms(tg: TG) -> int:
    """Новые тревоги наблюдения — один раз каждая."""
    last = int(await cache.redis.get("tg:last_alarm") or 0)
    sent = 0
    async with SessionLocal() as db:
        if last == 0:  # первый запуск — старое не присылаем
            top = await db.scalar(select(EngineEvent.id).order_by(EngineEvent.id.desc()).limit(1))
            await cache.redis.set("tg:last_alarm", top or 0)
            return 0
        rows = list(
            await db.scalars(
                select(EngineEvent)
                .where(EngineEvent.id > last, EngineEvent.kind.in_(("alarm", "ok")))
                .order_by(EngineEvent.id)
            )
        )
        admins = [
            u.telegram_chat_id
            for u in await db.scalars(select(User).where(User.is_admin.is_(True)))
            if u.telegram_chat_id
        ]
        for e in rows:
            chats = admins
            if e.account_id:
                chat, _ = await _chat_of_account(db, str(e.account_id))
                chats = [chat] if chat else []
            icon = "⚠" if e.kind == "alarm" else "✓"
            for c in chats:
                await tg.send(c, f"{icon} {e.message}")
                sent += 1
            last = e.id
    await cache.redis.set("tg:last_alarm", last)
    return sent


async def daily_report(tg: TG, day: str) -> int:
    """Отчёт за прошедшие сутки (UTC) — каждому привязанному с кабинетами."""
    if not await cache.redis.set(f"tg:daily:{day}", "1", nx=True, ex=3 * 86400):
        return 0
    n = 0
    async with SessionLocal() as db:
        users = list(await db.scalars(select(User).where(User.telegram_chat_id.is_not(None))))
        for u in users:
            accounts = await _accounts(db, u.id)
            if not accounts:
                continue
            d = datetime.strptime(day, "%Y%m%d").strftime("%d.%m.%Y")
            lines = [f"📊 Отчёт за {d} (UTC)"]
            for a in accounts:
                lines += ["", "━━━━━━━━━━━━", *await account_lines(a, day)]
            lines += ["", "⚠️ Прошлые результаты не обещают будущих."]
            await tg.send(u.telegram_chat_id, "\n".join(lines))
            n += 1
    return n


async def timers_loop(tg: TG) -> None:
    while True:
        try:
            await send_alarms(tg)
            now = datetime.now(UTC)
            if now.hour == 0 and now.minute >= 5:
                await daily_report(tg, (now - timedelta(days=1)).strftime("%Y%m%d"))
        except Exception:
            log.exception("тревоги / отчёт")
        await asyncio.sleep(20)


async def updates_loop(tg: TG) -> None:
    offset = int(await cache.redis.get("tg:offset") or 0)
    while True:
        try:
            data = await tg.call("getUpdates", offset=offset, timeout=30)
            for upd in data.get("result") or []:
                offset = upd["update_id"] + 1
                await cache.redis.set("tg:offset", offset)
                try:
                    await handle_update(tg, upd)
                except Exception:
                    log.exception("команда")
        except httpx.HTTPError as e:
            log.warning("telegram недоступен: %s", type(e).__name__)
            await asyncio.sleep(10)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # в адресах запросов — токен
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        log.info("нет токена (секрет SUNSCRYPT_TELEGRAM_TOKEN) — бот ждёт")
        while True:
            hb = json.dumps({"ts": time.time(), "token": False})
            await cache.redis.set("hb:tgbot", hb, ex=600)
            await asyncio.sleep(300)
    tg = TG(token)
    me = await tg.call("getMe")
    log.info("бот: @%s", (me.get("result") or {}).get("username"))
    await tg.call(
        "setMyCommands",
        commands=[
            {"command": "status", "description": "Состояние кабинетов и позиции"},
            {"command": "report", "description": "Отчёт за сегодня"},
            {"command": "stop", "description": "Аварийная остановка торговли"},
            {"command": "help", "description": "Справка"},
        ],
    )
    await asyncio.gather(updates_loop(tg), fills_loop(tg), timers_loop(tg))


if __name__ == "__main__":
    asyncio.run(main())
