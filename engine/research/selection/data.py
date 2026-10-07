"""Данные для отбора пар: часовые свечи и фандинг Binance USDT-M
(data.binance.vision), кэш — engine/var/data/selection/*.parquet.

    python research/selection/data.py
"""

from __future__ import annotations

import io
import os
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly"
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "var", "data", "selection")
MONTHS = [p.strftime("%Y-%m") for p in pd.period_range("2023-07", "2026-09", freq="M")]
# Крупные перпетуалы, торгуемые и на Bybit, без переименований за период.
CANDIDATES = """BTCUSDT ETHUSDT SOLUSDT XRPUSDT BNBUSDT ADAUSDT DOGEUSDT AVAXUSDT LINKUSDT DOTUSDT
LTCUSDT BCHUSDT TRXUSDT ATOMUSDT ETCUSDT FILUSDT NEARUSDT APTUSDT ARBUSDT OPUSDT SUIUSDT INJUSDT
UNIUSDT AAVEUSDT XLMUSDT HBARUSDT ICPUSDT 1000PEPEUSDT 1000SHIBUSDT LDOUSDT SANDUSDT MANAUSDT
AXSUSDT GALAUSDT APEUSDT CRVUSDT RUNEUSDT DYDXUSDT STXUSDT IMXUSDT GRTUSDT ALGOUSDT VETUSDT
THETAUSDT EGLDUSDT""".split()


def get(url: str, tries: int = 6) -> bytes | None:
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2**k)
        except Exception:
            time.sleep(2**k)
    raise RuntimeError(url)


def csv_of(b: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(b))
    raw = z.read(z.namelist()[0]).decode()
    head = 0 if not raw[0].isdigit() else None
    return pd.read_csv(io.StringIO(raw), header=head)


def klines(sym: str) -> pd.DataFrame | None:
    parts = []
    for m in MONTHS:
        b = get(f"{BASE}/klines/{sym}/1h/{sym}-1h-{m}.zip")
        if b is None:
            if m < "2026-09":
                return None  # нет месяца — пара не годится
            continue
        df = csv_of(b).iloc[:, :8]
        df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "amount"]
        parts.append(df)
    df = pd.concat(parts)
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms")
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    return df[["open", "high", "low", "close", "volume", "amount"]].astype(float)


def funding(sym: str) -> pd.Series:
    parts = []
    for m in MONTHS:
        b = get(f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
        if b is not None:
            df = csv_of(b)
            df.columns = ["calc_time", "interval", "rate"][: len(df.columns)]
            parts.append(df)
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts)
    ts = pd.to_datetime(df["calc_time"].astype("int64"), unit="ms").dt.floor("h")
    return pd.Series(df["rate"].astype(float).values, index=ts).groupby(level=0).last().sort_index()


def one(sym: str) -> tuple[str, str]:
    path = os.path.join(OUT, f"{sym}.parquet")
    if os.path.exists(path):
        return sym, "кэш"
    k = klines(sym)
    if k is None:
        return sym, "нет полной истории — пропуск"
    f = funding(sym)
    k["funding"] = f.reindex(k.index)
    k.to_parquet(path)
    return sym, f"{len(k)} свечей"


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(12) as ex:
        for sym, msg in ex.map(one, CANDIDATES):
            print(f"{sym}: {msg}", flush=True)
