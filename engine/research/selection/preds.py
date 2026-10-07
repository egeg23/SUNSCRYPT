"""Прогнозы дообученной Kronos-small во всех решающих точках (00/08/16 UTC)
валидации и теста, по паре — engine/var/data/selection/preds/<SYM>.parquet.
Пачками (несколько точек за один проход), с продолжением после обрыва.

    python research/selection/preds.py SYM [SYM ...]
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd
import torch

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)
from sunscrypt_engine.fastkronos import FastKronos, load, prepare  # noqa: E402

DATA = os.path.join(ROOT, "var", "data", "selection")
MODEL = os.path.join(ROOT, "var", "models", "ft_small_s300")
H, CONTEXT, S, BATCH = 8, 256, 16, 32
START = pd.Timestamp("2024-06-15")  # с запасом на 30 прошлых решений для z до 2024-07


def decision_points(df: pd.DataFrame) -> list[int]:
    """Индексы свечей, закрывающихся в 00/08/16 UTC (индекс — время открытия)."""
    close = df.index + pd.Timedelta(hours=1)
    ok = (close.hour % H == 0) & (df.index >= START)
    return [i for i in np.flatnonzero(ok) if i >= CONTEXT - 1]


def run(sym: str, fk: FastKronos) -> None:
    out = os.path.join(DATA, "preds", f"{sym}.parquet")
    df = pd.read_parquet(os.path.join(DATA, f"{sym}.parquet"))
    pts = decision_points(df)
    done = pd.read_parquet(out) if os.path.exists(out) else pd.DataFrame(columns=["rhat", "pup", "sd"])
    todo = [i for i in pts if (df.index[i] + pd.Timedelta(hours=1)) not in done.index]
    bar = pd.Timedelta(hours=1)
    rows, t0 = [], time.time()
    for b in range(0, len(todo), BATCH):
        chunk = todo[b : b + BATCH]
        xs, xss, yss, mus, sds = [], [], [], [], []
        for i in chunk:
            w = df.iloc[i - CONTEXT + 1 : i + 1]
            fut = pd.date_range(w.index[-1] + bar, periods=H, freq=bar)
            xn, x_s, y_s, mu, sd = prepare(w, w.index, fut)
            xs.append(xn), xss.append(x_s), yss.append(y_s), mus.append(mu), sds.append(sd)
        z = fk.generate(np.stack(xs), np.stack(xss), np.stack(yss), H, S=S)
        for k, i in enumerate(chunk):
            close = z[k, :, -1, 3] * (sds[k][3] + 1e-5) + mus[k][3]
            r = close / df["close"].iloc[i] - 1
            rows.append((df.index[i] + bar, float(r.mean()), float((r > 0).mean()), float(r.std())))
        if len(rows) >= 256 or b + BATCH >= len(todo):
            new = pd.DataFrame(rows, columns=["ts", "rhat", "pup", "sd"]).set_index("ts")
            done = pd.concat([done, new]).sort_index()
            done.to_parquet(out)
            rate = (time.time() - t0) / max(1, b + len(chunk))
            print(f"{sym}: {len(done)}/{len(pts)} ({rate:.2f} с/точку)", flush=True)
            rows = []


if __name__ == "__main__":
    torch.set_num_threads(int(os.environ.get("KRONOS_THREADS", "1")))
    os.makedirs(os.path.join(DATA, "preds"), exist_ok=True)
    tok, m, ctx = load("small", MODEL)
    fk = FastKronos(tok, m, ctx)
    for s in sys.argv[1:]:
        run(s, fk)
