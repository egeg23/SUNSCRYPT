"""Наблюдение (app/watch.py): тревога один раз на беду, «исправилось» — когда ушла."""

import asyncio
import json
import os
import time

from sqlalchemy import create_engine, text

from tests.conftest import live


def _run() -> int:
    from redis.asyncio import Redis

    from app import watch

    async def go():
        r = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        try:
            return await watch.main(r)
        finally:
            await r.aclose()

    return asyncio.run(go())


def _events(eng, since):
    with eng.connect() as c:
        return c.execute(
            text(
                "SELECT kind, message FROM engine_events "
                "WHERE kind IN ('alarm', 'ok') AND ts >= :t ORDER BY id"
            ),
            {"t": since},
        ).all()


@live
def test_alarm_once_then_ok(client):
    import redis

    eng = create_engine(os.environ["DATABASE_URL"])
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    with eng.connect() as c:
        since = c.execute(text("SELECT now()")).scalar()
        trading = [
            str(x)
            for x in c.execute(
                text("SELECT id FROM exchange_accounts WHERE trading_enabled AND NOT stopped")
            ).scalars()
        ]

    # Redis пуст (фикстура client): сигналы молчат — тревога.
    assert _run() == 1
    assert _run() == 1  # повторно не пишет
    ev = _events(eng, since)
    signals = [m for k, m in ev if "сигналов" in m]
    assert signals == ["Сервис сигналов молчит больше 10 минут"]

    # Всё ожило — «исправилось».
    now_ms = int(time.time() * 1000)
    r.set("hb:signals", json.dumps({"ts": now_ms}))
    for aid in trading:
        r.set(f"hb:acct:{aid}", json.dumps({"ts": now_ms}))
    with eng.begin() as c:
        c.execute(text("UPDATE exchange_accounts SET status = 'ok' WHERE trading_enabled"))
    assert _run() == 0
    ev = _events(eng, since)
    assert ("ok", "Исправилось: Сервис сигналов молчит больше 10 минут") in ev
    assert [k for k, _ in ev].count("alarm") == [k for k, _ in ev].count("ok")
    eng.dispose()
