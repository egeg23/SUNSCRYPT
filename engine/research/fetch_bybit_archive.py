"""Download Bybit linear-perp klines from the public archive (public.bybit.com/kline_for_metatrader4).
The archive is Bybit's own data; it covers 2020 .. Nov 2024. The REST API (api.bybit.com) is geo-blocked from this container."""
import io, gzip, sys, re, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

BASE = "https://public.bybit.com/kline_for_metatrader4"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
INTERVALS = ["5", "15", "60"]
YEARS = ["2022", "2023", "2024"]

def get(url, tries=6):
    import time
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 ** k)

def files_for(sym, year):
    html = get(f"{BASE}/{sym}/{year}/").decode()
    return re.findall(r'href="([^"]+\.csv\.gz)"', html)

def load(sym, year, fn):
    raw = gzip.decompress(get(f"{BASE}/{sym}/{year}/{fn}"))
    df = pd.read_csv(io.BytesIO(raw), header=None, names=["ts", "open", "high", "low", "close", "volume"])
    return fn.split("_")[1], df

def main():
    jobs = []
    for s in SYMBOLS:
        for y in YEARS:
            try:
                for fn in files_for(s, y):
                    if fn.split("_")[1] in INTERVALS:
                        jobs.append((s, y, fn))
            except Exception as e:
                print("skip", s, y, e)
    print(len(jobs), "files")
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: (j[0], *load(*j)), jobs))
    for s in SYMBOLS:
        for iv in INTERVALS:
            parts = [d for (sym, i, d) in res if sym == s and i == iv]
            if not parts:
                continue
            df = pd.concat(parts)
            # MT4 archive timestamps are UTC+3 (verified: return corr with Binance = 1.0 only at -3h)
            df["ts"] = pd.to_datetime(df["ts"], format="%Y.%m.%d %H:%M") - pd.Timedelta(hours=3)
            df = df.drop_duplicates("ts").sort_values("ts").set_index("ts")
            df.to_parquet(f"data/bybit/{s}_{iv}.parquet")
            print(s, iv, len(df), df.index.min(), df.index.max())

if __name__ == "__main__":
    main()
