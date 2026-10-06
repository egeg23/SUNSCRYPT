"""Signal sources for KronosStrategy: replay of saved research forecasts, or live Kronos inference."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

from paths import DATA_DIR, MODEL_DIR, RESULTS_DIR  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))


def _sym(iid) -> str:
    return str(iid).split("-")[0]          # "BTCUSDT-LINEAR.BYBIT" -> "BTCUSDT"


class ReplaySignals:
    """Forecasts saved by src/run_preds.py (results/preds/<tag>_<period>_<sym>_<tf>.npz), keyed by bar open time."""
    needs_history = False

    def __init__(self, tag, period, tf, symbols, bar_minutes):
        self.bar_ns = bar_minutes * 60_000_000_000
        self.map = {}
        for s in symbols:
            d = np.load(f"{RESULTS_DIR}/preds/{tag}_{period}_{s}_{tf}.npz")
            sr = d["samples"][:, :, -1] / d["close"][:, None] - 1
            for t, r in zip(d["t"], sr):
                self.map[(s, int(t) * 60_000_000_000)] = (float(r.mean()), float((r > 0).mean()), float(r.std()))

    def signal(self, iid, ts_close, bars):
        return self.map.get((_sym(iid), ts_close - self.bar_ns))


class KronosSignals:
    """Live inference with the fast KV-cached Kronos on the strategy's bar buffer."""
    needs_history = True

    def __init__(self, model="small", model_path=None, horizon=8, context=256, samples=16, bar_minutes=60):
        import torch
        from fastkronos import FastKronos, load
        tok, m, ctx = load(model, model_path)
        self.fk = FastKronos(tok, m, ctx)
        self.h, self.L, self.S = horizon, context, samples
        self.bar = pd.Timedelta(minutes=bar_minutes)
        torch.set_num_threads(int(os.environ.get("KRONOS_THREADS", "4")))

    def signal(self, iid, ts_close, bars):
        from fastkronos import prepare
        if len(bars) < self.L:
            return None
        rows = list(bars)[-self.L:]
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.pop("ts"), unit="ns") - self.bar          # index = bar open time
        df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        fut = pd.date_range(df.index[-1] + self.bar, periods=self.h, freq=self.bar)
        xn, xs, ys, mu, sd = prepare(df, df.index, fut)
        z = self.fk.generate(xn[None], xs[None], ys[None], self.h, S=self.S)
        close = z[0, :, -1, 3] * (sd[3] + 1e-5) + mu[3]
        r = close / df["close"].iloc[-1] - 1
        return float(r.mean()), float((r > 0).mean()), float(r.std())


class MomentumSignals:
    """Baseline without any model: expected return = return over the last `horizon` bars."""
    needs_history = True

    def __init__(self, horizon=8):
        self.h = horizon

    def signal(self, iid, ts_close, bars):
        if len(bars) <= self.h:
            return None
        c_now, c_past = bars[-1][4], bars[-1 - self.h][4]
        return c_now / c_past - 1, 1.0, 0.0
