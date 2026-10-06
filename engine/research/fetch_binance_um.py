"""Out-of-sample test data: Binance USDT-M perpetual klines + funding from data.binance.vision
(Bybit REST is geo-blocked here and the Bybit kline archive stops at Nov 2024). Prices track Bybit perps closely."""
import io, zipfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
INTERVALS = ["5m", "15m", "1h", "4h"]
MONTHS = [p.strftime("%Y-%m") for p in pd.period_range("2024-01", "2026-09", freq="M")]

def get(url, tries=6):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** k)
        except Exception:
            time.sleep(2 ** k)
    raise RuntimeError(url)

def read_zip(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    raw = z.read(z.namelist()[0]).decode()
    first = raw.split("\n", 1)[0]
    df = pd.read_csv(io.StringIO(raw), header=0 if not first[0].isdigit() else None)
    return df

def kl(job):
    s, iv, mth = job
    b = get(f"{BASE}/klines/{s}/{iv}/{s}-{iv}-{mth}.zip")
    if b is None:
        return job, None
    df = read_zip(b).iloc[:, :8]
    df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "amount"]
    return job, df

def fr(job):
    s, mth = job
    b = get(f"{BASE}/fundingRate/{s}/{s}-fundingRate-{mth}.zip")
    return job, (None if b is None else read_zip(b))

if __name__ == "__main__":
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(kl, [(s, i, m) for s in SYMBOLS for i in INTERVALS for m in MONTHS]))
        fres = list(ex.map(fr, [(s, m) for s in SYMBOLS for m in MONTHS]))
    for s in SYMBOLS:
        for iv in INTERVALS:
            parts = [d for (j, d) in res if j[0] == s and j[1] == iv and d is not None]
            df = pd.concat(parts)
            df["ts"] = pd.to_datetime(df.open_time.astype("int64"), unit="ms")
            df = df.drop_duplicates("ts").sort_values("ts").set_index("ts")[["open", "high", "low", "close", "volume", "amount"]].astype(float)
            df.to_parquet(f"data/binance/{s}_{iv}.parquet")
            print(s, iv, len(df), df.index.min(), df.index.max())
        parts = [d for (j, d) in fres if j[0] == s and d is not None]
        f = pd.concat(parts)
        f.columns = ["calc_time", "interval_h", "rate"][:len(f.columns)] if len(f.columns) == 3 else f.columns
        f.to_parquet(f"data/binance/{s}_funding.parquet")
        print(s, "funding", len(f), f.columns.tolist())
