"""Отчёт о движке для лога (Actions публичны — без почт и ключей):
кабинеты с торговлей, сердцебиение исполнителей, сделки, сверка, события.

    python -m app.engine_report
"""

import asyncio
import json
import time

from sqlalchemy import func, select

from app.cache import redis
from app.db import SessionLocal
from app.models import EngineEvent, ExchangeAccount, Trade


async def main() -> None:
    now = time.time()
    hb = await redis.get("hb:signals")
    print(f"▸ Сигналы: {'живы' if hb else 'нет сердцебиения'}")
    async with SessionLocal() as db:
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
