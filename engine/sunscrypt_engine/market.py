"""Свечи Bybit (публичный REST, без ключей). Цены демо и основного счёта
одинаковые — берём с основного api.bybit.com."""

from __future__ import annotations

import time

import httpx
import pandas as pd

BYBIT = "https://api.bybit.com"


def klines(sym: str, minutes: int = 60, limit: int = 1000, client: httpx.Client | None = None) -> pd.DataFrame:
    """Закрытые свечи по возрастанию времени; индекс — время открытия (UTC)."""
    c = client or httpx.Client(timeout=20)
    r = c.get(
        f"{BYBIT}/v5/market/kline",
        params={"category": "linear", "symbol": sym, "interval": str(minutes), "limit": limit},
    )
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit kline {sym}: {data.get('retMsg')}")
    rows = data["result"]["list"]  # новые сначала
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    df = df.astype(float)
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
    df = df.set_index("ts").sort_index()
    now = pd.Timestamp(time.time(), unit="s")
    df = df[df.index + pd.Timedelta(minutes=minutes) <= now]  # только закрытые
    df["amount"] = df.pop("turnover")
    return df[["open", "high", "low", "close", "volume", "amount"]]
