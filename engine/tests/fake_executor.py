"""Заглушка исполнителя для проверки диспетчера: пишет сердцебиение и одно
исполнение, по флагу остановки «закрывает позиции», по FAKE_CRASH падает."""

import json
import os
import signal
import sys
import time

import redis

aid = os.environ["SUNS_ACCOUNT_ID"]
assert os.environ["SUNS_API_KEY"] and "MASTER_KEY" not in os.environ
r = redis.Redis.from_url(os.environ["REDIS_URL"])
if r.get("fake:crash") == b"1":
    sys.exit(3)
mode = os.environ["SUNS_MODE"]
assert mode == "demo" or os.environ.get("SUNS_REAL_CONFIRMED") == "yes"
r.rpush("fake:log", f"start:{mode}")
if r.incr("fake:alive") > 1:
    r.rpush("fake:log", "ДВА ПРОЦЕССА")
r.xadd(f"fills:{aid}", {
    "mode": mode,
    "trade_id": f"exec-{aid[:6]}-{mode}", "venue_order_id": "o1", "sym": "BTCUSDT", "side": "buy",
    "qty": "0.01", "price": "80000", "fee": "0.16", "fee_ccy": "USDT", "liquidity": "MAKER",
    "ts": str(int(time.time() * 1000)),
})
flat_logged = False


def bye(*_):
    r.decr("fake:alive")
    sys.exit(0)


signal.signal(signal.SIGINT, bye)
while True:
    halted = r.get(f"stop:acct:{aid}") == b"1"
    if halted and not flat_logged:
        r.rpush("fake:log", f"flat:{mode}")
        flat_logged = True
    r.set(f"hb:acct:{aid}", json.dumps({
        "ts": int(time.time() * 1000), "halted": "stop" if halted else None,
        "positions": {} if halted else {"BTCUSDT": 0.01}, "open_orders": 0, "pnl": 0,
    }))
    time.sleep(0.2)
