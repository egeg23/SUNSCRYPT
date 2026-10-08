"""Отчёт о движке для лога (Actions публичны — без почт и ключей):
кабинеты с торговлей, сердцебиение исполнителей, сделки, сверка, события.

    python -m app.engine_report
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.cache import redis
from app.db import SessionLocal
from app.models import EngineEvent, EquitySnapshot, ExchangeAccount, Trade, User


async def _days(db, a: ExchangeAccount) -> None:
    """Итоги трёх последних суток UTC: результат, сделки, комиссии, баланс."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for k in (2, 1, 0):
        start = today - timedelta(days=k)
        end = start + timedelta(days=1)
        day = start.strftime("%Y%m%d")
        total = await redis.get(f"daytotal:{a.id}:{day}")
        net = await redis.hgetall(f"daynet:{a.id}:{a.mode}:{day}")
        trades, fees = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(Trade.fee), 0)).where(
                    Trade.account_id == a.id, Trade.ts >= start, Trade.ts < end
                )
            )
        ).one()
        eq = [
            await db.scalar(
                select(EquitySnapshot.equity_usd)
                .where(
                    EquitySnapshot.account_id == a.id,
                    EquitySnapshot.ts >= start,
                    EquitySnapshot.ts < end,
                )
                .order_by(EquitySnapshot.ts.asc() if first else EquitySnapshot.ts.desc())
                .limit(1)
            )
            for first in (True, False)
        ]
        parts = []
        if total is not None:
            parts.append(f"результат с позициями {float(total):+.2f}")
        if net:
            parts.append(
                f"по сделкам {float(net.get(b'net', 0)):+.2f} ({int(net.get(b'n', 0))} шт.)"
            )
        parts.append(f"сделок в журнале {trades}, комиссии {float(fees):.2f}")
        if eq[0] is not None:
            parts.append(f"баланс {eq[0]:.2f} → {eq[1]:.2f}")
        print(f"    {start:%m-%d}: " + "; ".join(parts))
    # Самые дорогие сделки за неделю: комиссия больше 1% объёма — ошибка записи;
    # огромный объём — не наша сделка (ручная на том же счёте) или сбой размера.
    top = await db.scalars(
        select(Trade)
        .where(Trade.account_id == a.id, Trade.ts >= today - timedelta(days=7))
        .order_by(Trade.fee.desc())
        .limit(3)
    )
    for t in top:
        odd = "⚠ " if t.fee > 0.01 * t.qty * t.price else ""
        print(
            f"    {odd}дорогая: комиссия {t.fee:.2f} {t.fee_ccy}, объём {t.qty * t.price:.0f}: "
            f"{t.ts:%m-%d %H:%M} {t.mode} {t.sym} {t.side} {t.qty}@{t.price} "
            f"{t.liquidity} ({t.source})"
        )


async def main() -> None:
    now = time.time()
    hb = await redis.get("hb:signals")
    print(f"▸ Сигналы: {'живы' if hb else 'нет сердцебиения'}")
    async with SessionLocal() as db:
        linked = await db.scalar(
            select(func.count()).select_from(User).where(User.telegram_chat_id.is_not(None))
        )
        print(f"▸ Telegram: привязано аккаунтов — {linked}")
        accounts = list(await db.scalars(select(ExchangeAccount)))
        print(
            f"▸ Кабинетов: {len(accounts)}, с торговлей: {sum(a.trading_enabled for a in accounts)}"
        )
        for a in accounts:
            tag = f"{str(a.id)[:8]} {a.mode}"  # mode — активный счёт
            raw = await redis.get(f"hb:acct:{a.id}")
            h = json.loads(raw) if raw else None
            n = await db.scalar(
                select(func.count()).select_from(Trade).where(Trade.account_id == a.id)
            )
            state = "торговля вкл" if a.trading_enabled else "торговля выкл"
            if a.stopped:
                state += ", аварийная остановка"
            print(f"  [{tag}] {state}; ключ {a.status}; сделок в журнале {n}")
            bal = f"{a.equity_usd:.2f}" if a.equity_usd is not None else "—"
            print(f"    баланс USDT {bal}; капитал стратегии {a.capital_usd}, плечо {a.leverage}")
            await _days(db, a)
            if h:
                print(
                    f"    исполнитель: {now - h['ts'] / 1000:.0f} с назад; "
                    f"позиции {h['positions']}; PnL {h['pnl']}; "
                    f"стоит: {h['halted']}; ордеров {h['open_orders']}"
                )
            rec = await redis.get(f"recon:{a.id}")
            if rec:
                r = json.loads(rec)
                print(
                    f"    сверка: Bybit {r['bybit']}, журнал {r['journal']}, "
                    f"дописано {r['added']}, лишних {r['extra']}"
                )
            events = await db.scalars(
                select(EngineEvent)
                .where(EngineEvent.account_id == a.id)
                .order_by(EngineEvent.ts.desc())
                .limit(6)
            )
            for e in events:
                print(f"    {e.ts:%m-%d %H:%M} {e.kind}: {e.message}")


if __name__ == "__main__":
    asyncio.run(main())
