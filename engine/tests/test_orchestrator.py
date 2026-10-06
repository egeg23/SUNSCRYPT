"""Диспетчер на живых PostgreSQL и Redis; исполнитель и Bybit подменены."""

import asyncio
import base64
import json
import os
import sys
import uuid

import pytest

if os.environ.get("SUNSCRYPT_TEST_LIVE") != "1":
    pytest.skip("нужны PostgreSQL и Redis", allow_module_level=True)

os.environ.setdefault("MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("DB_NULLPOOL", "1")
os.environ["SUNS_EXECUTOR_MODULE"] = "tests.fake_executor"
os.environ["SIGNAL_PAIRS"] = "BTCUSDT"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import bybit, crypto  # noqa: E402
from app.accounts import KEY_PURPOSE, SECRET_PURPOSE  # noqa: E402
from sunscrypt_engine import orchestrator as orch  # noqa: E402

EXECS = []


def bybit_handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/v5/execution/list":
        return httpx.Response(200, json={"retCode": 0, "result": {"list": EXECS, "nextPageCursor": ""}})
    if p == "/v5/account/wallet-balance":
        return httpx.Response(200, json={"retCode": 0, "result": {"list": [{"totalEquity": "5000"}]}})
    return httpx.Response(200, json={"retCode": 0, "result": {}})


@pytest.fixture
def db():
    eng = create_engine(os.environ["DATABASE_URL"])
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def fake_bybit(monkeypatch):
    monkeypatch.setattr(bybit, "transport", httpx.MockTransport(bybit_handler))
    import redis

    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    r.flushdb()
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:  # кабинеты прошлых прогонов зашифрованы другим ключом
        c.execute(text("DELETE FROM exchange_accounts"))
    eng.dispose()
    # Свой асинхронный клиент на каждый тест: у каждого asyncio.run свой цикл.
    from redis.asyncio import Redis

    monkeypatch.setattr(orch, "redis", Redis.from_url(os.environ["REDIS_URL"]))
    yield r


def make_account(db, enabled=True, real_key=False) -> str:
    uid, aid = uuid.uuid4(), uuid.uuid4()
    with db.begin() as c:
        c.execute(text("INSERT INTO users (id, email, password_hash, is_admin) VALUES (:i, :e, 'x', false)"),
                  {"i": uid, "e": f"{uid.hex[:8]}@example.com"})
        c.execute(text(
            "INSERT INTO exchange_accounts (id, user_id, name, mode, status, trading_enabled, leverage, "
            "daily_loss_pct) VALUES (:a, :u, 'Демо', 'demo', 'ok', :en, 1, 5)"),
            {"a": aid, "u": uid, "en": enabled})
        for mode in ("demo", "real") if real_key else ("demo",):
            c.execute(text(
                "INSERT INTO account_keys (id, account_id, mode, api_key_enc, api_secret_enc, key_tail, "
                "permissions, ips, warnings, status) VALUES (:id, :a, :m, :k, :s, :t, '{}', '[]', '[]', 'ok')"),
                {"id": uuid.uuid4(), "a": aid, "m": mode, "t": mode[:4],
                 "k": crypto.encrypt(f"GOOD{mode}key12345".encode(), KEY_PURPOSE),
                 "s": crypto.encrypt(b"secret1234567", SECRET_PURPOSE)})
    return str(aid)


async def ticks(o, n=1, pause=0.5):
    for _ in range(n):
        await o.tick()
        await o.drain_fills()
        await asyncio.sleep(pause)


def test_start_journal_wind_down(db, fake_bybit):
    aid = make_account(db)

    async def scenario():
        o = orch.Orchestrator()
        await ticks(o, 3)
        pr = o.procs[aid]
        assert pr.p and pr.p.returncode is None
        with db.connect() as c:
            n = c.execute(text("SELECT count(*) FROM trades WHERE account_id = :a"), {"a": aid}).scalar()
        assert n == 1
        # Выключили торговлю → флаг остановки → «позиции закрыты» → процесс погашен.
        with db.begin() as c:
            c.execute(text("UPDATE exchange_accounts SET trading_enabled = false WHERE id = :a"), {"a": aid})
        await ticks(o, 4)
        assert fake_bybit.get(f"stop:acct:{aid}") == b"1"
        assert pr.p is None  # погашен намеренно
        # Сверка: у Bybit две сделки, одна уже в журнале — дописывается вторая.
        with db.begin() as c:
            c.execute(text("UPDATE exchange_accounts SET trading_enabled = true WHERE id = :a"), {"a": aid})
        EXECS[:] = [
            {"execId": f"exec-{aid[:6]}-demo", "symbol": "BTCUSDT", "side": "Buy", "execQty": "0.01",
             "execPrice": "80000", "execFee": "0.16", "execTime": "1790000000000", "execType": "Trade",
             "isMaker": True},
            {"execId": "missing-1", "symbol": "BTCUSDT", "side": "Sell", "execQty": "0.01",
             "execPrice": "80100", "execFee": "0.44", "execTime": "1790000600000", "execType": "Trade",
             "isMaker": False},
        ]
        with db.begin() as c:
            c.execute(text("UPDATE trades SET ts = now() WHERE account_id = :a"), {"a": aid})
        await o.reconcile()
        recon = json.loads(fake_bybit.get(f"recon:{aid}"))
        assert recon["added"] == 1 and recon["bybit"] == 2
        await o.snapshot_equity()
        for p in o.procs.values():
            if p.p and p.p.returncode is None:
                p.p.kill()

    asyncio.run(scenario())
    with db.connect() as c:
        kinds = [r[0] for r in c.execute(text(
            "SELECT kind FROM engine_events WHERE account_id = :a ORDER BY id"), {"a": aid})]
        eq = c.execute(text("SELECT equity_usd FROM equity_snapshots WHERE account_id = :a"), {"a": aid}).scalar()
    assert kinds[:2] == ["start", "exit"] and "reconcile" in kinds
    assert eq == 5000


def test_crash_backoff(db, fake_bybit):
    aid = make_account(db)
    fake_bybit.set("fake:crash", "1")

    async def scenario():
        o = orch.Orchestrator()
        await ticks(o, 3, pause=1.0)
        pr = o.procs[aid]
        assert pr.fails >= 1 and pr.next_try > 0

    asyncio.run(scenario())
    with db.connect() as c:
        kinds = [r[0] for r in c.execute(text(
            "SELECT kind FROM engine_events WHERE account_id = :a"), {"a": aid})]
    assert "crash" in kinds


def test_global_stop_mirrored(db, fake_bybit):
    with db.begin() as c:
        c.execute(text("UPDATE system_flags SET value = true WHERE key = 'global_stop'"))
    try:
        asyncio.run(orch.Orchestrator().tick())
        assert fake_bybit.get("stop:global") == b"1"
    finally:
        with db.begin() as c:
            c.execute(text("UPDATE system_flags SET value = false WHERE key = 'global_stop'"))


def test_switch_demo_to_real_flattens_first_no_double_positions(db, fake_bybit):
    aid = make_account(db, real_key=True)
    with db.begin() as c:
        c.execute(text("UPDATE system_flags SET value = true WHERE key = 'real_trading_enabled'"))
    try:
        async def scenario():
            o = orch.Orchestrator()
            await ticks(o, 3)
            assert o.procs[aid].mode == "demo"
            with db.begin() as c:
                c.execute(text("UPDATE exchange_accounts SET mode = 'real' WHERE id = :a"), {"a": aid})
            await ticks(o, 8)
            assert o.procs[aid].mode == "real" and o.procs[aid].p.returncode is None
            for p in o.procs.values():
                if p.p and p.p.returncode is None:
                    p.p.kill()

        asyncio.run(scenario())
    finally:
        with db.begin() as c:
            c.execute(text("UPDATE system_flags SET value = false WHERE key = 'real_trading_enabled'"))
    log = [x.decode() for x in fake_bybit.lrange("fake:log", 0, -1)]
    assert log[:3] == ["start:demo", "flat:demo", "start:real"], log
    assert "ДВА ПРОЦЕССА" not in log
    with db.connect() as c:
        modes = sorted(m for (m,) in c.execute(text("SELECT mode FROM trades WHERE account_id = :a"), {"a": aid}))
        kinds = [k for (k,) in c.execute(text("SELECT kind FROM engine_events WHERE account_id = :a"), {"a": aid})]
    assert modes == ["demo", "real"] and "crash" not in kinds


def test_real_blocked_without_owner_flag(db, fake_bybit):
    aid = make_account(db, real_key=True)
    with db.begin() as c:
        c.execute(text("UPDATE exchange_accounts SET mode = 'real' WHERE id = :a"), {"a": aid})

    async def scenario():
        o = orch.Orchestrator()
        await ticks(o, 2)
        assert aid not in o.procs or o.procs[aid].p is None

    asyncio.run(scenario())
