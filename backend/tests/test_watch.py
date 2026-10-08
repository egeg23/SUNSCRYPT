"""Наблюдение (app/watch.py): тревога один раз на беду, «исправилось» — когда ушла."""

import asyncio
import json
import os
import time

import pytest
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


@live
def test_admin_sees_model_history_and_can_resume_pause(client):
    import redis

    from tests.helpers import owner_login

    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO model_events (version, action, champion, reason, metrics) "
                "VALUES ('ft-x', 'rejected', 'ft_small_s300', 'Не лучше чемпиона', '{}')"
            )
        )
    eng.dispose()
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    r.set("pause:kronos", "дрейф")
    r.set("pause:pair:ADAUSDT", "дрейф пары")
    owner_login(client)
    m = client.get("/api/admin/models").json()
    assert m["champion"] == "ft_small_s300" and m["paused"] == "дрейф"
    assert m["paused_pairs"] == {"ADAUSDT": "дрейф пары"}
    assert m["events"][0]["reason"] == "Не лучше чемпиона"
    m = client.post("/api/admin/models/resume", json={}).json()
    assert m["paused"] is None and m["events"][0]["action"] == "resumed"
    assert r.get("pause:kronos") is None and r.get("pause:pair:ADAUSDT") is None
    assert int(r.get("drift:since:ADAUSDT")) > 0  # дрейф пары считается заново


@live
def test_foreign_position_raises_alarm(client):
    import redis
    from redis.asyncio import Redis

    from app import watch

    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        aid = c.execute(
            text("SELECT id FROM exchange_accounts WHERE trading_enabled AND NOT stopped LIMIT 1")
        ).scalar()
    eng.dispose()
    if aid is None:
        pytest.skip("нет кабинета с торговлей")
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    r.set(
        f"hb:acct:{aid}",
        json.dumps({"ts": int(time.time() * 1000), "blocked": {"ADAUSDT": "позиция не наша"}}),
    )

    async def go():
        ar = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        try:
            return await watch.problems(ar)
        finally:
            await ar.aclose()

    out = asyncio.run(go())
    assert "ADAUSDT: позиция не наша" in out[f"foreign:{aid}:ADAUSDT"][1]
