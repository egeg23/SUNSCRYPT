"""Заглушка исполнителя для проверки диспетчера: пишет сердцебиение и одно
исполнение, по флагу остановки «закрывает позиции», по FAKE_CRASH падает."""

import json
import os
import sys
import time

import redis

aid = os.environ["SUNS_ACCOUNT_ID"]
assert os.environ["SUNS_API_KEY"] and "MASTER_KEY" not in os.environ
r = redis.Redis.from_url(os.environ["REDIS_URL"])
if r.get("fake:crash") == b"1":
    sys.exit(3)
r.xadd(f"fills:{aid}", {
    "trade_id": f"exec-{aid[:6]}-1", "venue_order_id": "o1", "sym": "BTCUSDT", "side": "buy",
    "qty": "0.01", "price": "80000", "fee": "0.16", "fee_ccy": "USDT", "liquidity": "MAKER",
    "ts": str(int(time.time() * 1000)),
})
while True:
    halted = r.get(f"stop:acct:{aid}") == b"1"
    r.set(f"hb:acct:{aid}", json.dumps({
        "ts": int(time.time() * 1000), "halted": "stop" if halted else None,
        "positions": {} if halted else {"BTCUSDT": 0.01}, "open_orders": 0, "pnl": 0,
    }))
    time.sleep(0.2)
