"""Наблюдение за сервисом: раз в несколько минут (cron на сервере) проверяет,
что движок жив и журнал сходится с Bybit. Новая беда → событие «alarm» в
журнале движка (видно в админке), ушла → «ok». Повторно об одной и той же
беде не пишет.

    python -m app.watch
"""

import asyncio
import json
import time
import uuid

from sqlalchemy import select

from app import cache
from app.db import SessionLocal
from app.models import EngineEvent, ExchangeAccount, SystemFlag

STATE = "watch:state"
HB_STALE_S = 180  # исполнитель шлёт сердцебиение раз в 15 с


async def problems(redis) -> dict[str, tuple[str | None, str]]:
    """{ключ беды: (id кабинета или None, текст)}."""
    out: dict[str, tuple[str | None, str]] = {}
    now = time.time()
    if not await redis.get("hb:signals"):
        out["signals"] = (None, "Сервис сигналов молчит больше 10 минут")
    async with SessionLocal() as db:
        stop = await db.get(SystemFlag, "global_stop")
        if stop and stop.value:
            return out  # всё остановлено намеренно
        accounts = await db.scalars(
            select(ExchangeAccount).where(
                ExchangeAccount.trading_enabled.is_(True), ExchangeAccount.stopped.is_(False)
            )
        )
        for a in accounts:
            aid, tag = str(a.id), str(a.id)[:8]
            if a.status != "ok":
                out[f"key:{aid}"] = (aid, f"Ключ Bybit кабинета {tag} не проходит проверку")
            raw = await redis.get(f"hb:acct:{aid}")
            age = now - json.loads(raw)["ts"] / 1000 if raw else None
            if age is None or age > HB_STALE_S:
                when = f"{age / 60:.0f} мин" if age is not None else "давно"
                out[f"hb:{aid}"] = (aid, f"Исполнитель кабинета {tag} молчит ({when})")
            rec = await redis.get(f"recon:{aid}")
            if rec:
                r = json.loads(rec)
                if r.get("extra"):
                    out[f"recon:{aid}"] = (
                        aid,
                        f"Журнал кабинета {tag} не сходится с Bybit: лишних сделок {r['extra']}",
                    )
    return out


def _uid(aid: str | None) -> uuid.UUID | None:
    return uuid.UUID(aid) if aid else None


async def main(redis=None) -> int:
    redis = redis or cache.redis
    found = await problems(redis)
    raw = await redis.get(STATE)
    before: dict[str, list] = json.loads(raw) if raw else {}
    async with SessionLocal() as db:
        for k, (aid, msg) in found.items():
            if k not in before:
                db.add(EngineEvent(account_id=_uid(aid), kind="alarm", message=msg))
        for k, (aid, msg) in before.items():
            if k not in found:
                uid = _uid(aid)
                if uid and not await db.get(ExchangeAccount, uid):
                    uid = None  # кабинет удалён
                db.add(EngineEvent(account_id=uid, kind="ok", message=f"Исправилось: {msg}"))
        await db.commit()
    await redis.set(STATE, json.dumps({k: list(v) for k, v in found.items()}))
    for _aid, msg in found.values():
        print(f"⚠ {msg}")
    if not found:
        print("▸ Наблюдение: всё в порядке")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
