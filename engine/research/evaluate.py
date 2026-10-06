"""Forecast metrics + cost-aware backtest on saved walk-forward predictions."""
import glob, os
import numpy as np, pandas as pd
from scipy.stats import spearmanr

ROOT = os.path.join(os.path.dirname(__file__), "..")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
HORIZON = {"5m": 12, "15m": 8, "1h": 8, "4h": 6}
BAR_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
# per side: Bybit VIP0 linear perp taker 0.055 % + 0.02 % slippage; maker 0.02 %, no slippage
COSTS = {"taker": 0.00055 + 0.0002, "maker": 0.0002, "zero": 0.0}

_bars, _fund = {}, {}


def bars(sym, tf):
    if (sym, tf) not in _bars:
        _bars[sym, tf] = pd.read_parquet(f"{ROOT}/data/binance/{sym}_{tf}.parquet")["close"].values
    return _bars[sym, tf]


def funding(sym):
    if sym not in _fund:
        f = pd.read_parquet(f"{ROOT}/data/binance/{sym}_funding.parquet")
        _fund[sym] = (f.calc_time.values // 60000, f.rate.values)   # minutes
    return _fund[sym]


def load(tag, period, sym, tf):
    p = f"{ROOT}/results/preds/{tag}_{period}_{sym}_{tf}.npz"
    if not os.path.exists(p):
        return None
    d = dict(np.load(p))
    H = HORIZON[tf]
    c = d["close"]
    d["r"] = d["fut_close"][:, -1] / c - 1                          # realised H-bar return
    sr = d["samples"][:, :, -1] / c[:, None] - 1                     # sampled H-bar returns [N,S]
    d["sr"] = sr
    d["rhat"] = sr.mean(1)
    d["pup"] = (sr > 0).mean(1)
    d["sd"] = sr.std(1)
    # bias-corrected signal: z-score of rhat vs its own trailing history (strictly past decisions only)
    rh = pd.Series(d["rhat"])
    mu = rh.shift(1).rolling(30, min_periods=10).mean()
    sg = rh.shift(1).rolling(30, min_periods=10).std()
    d["z"] = ((rh - mu) / sg).fillna(0).values
    cl = bars(sym, tf)
    idx = d["idx"]
    d["past"] = c / cl[idx - H] - 1                                  # past H-bar return (momentum)
    # funding paid by a long between entry (close of bar t) and exit
    ft, fr = funding(sym)
    t_entry = d["t"] + BAR_MIN[tf]
    t_exit = t_entry + H * BAR_MIN[tf]
    cs = np.concatenate([[0], np.cumsum(fr)])
    d["fund"] = cs[np.searchsorted(ft, t_exit, "right")] - cs[np.searchsorted(ft, t_entry, "right")]
    d["contig"] = np.r_[False, np.diff(idx) == H]                   # previous trade ends where this starts
    return d


def forecast_metrics(d, pred):
    r = d["r"]
    nz = r != 0
    out = {
        "n": len(r),
        "dir_acc": float((np.sign(pred[nz]) == np.sign(r[nz])).mean()),
        "IC": float(np.corrcoef(pred, r)[0, 1]) if pred.std() > 0 else np.nan,
        "RankIC": float(spearmanr(pred, r).correlation) if pred.std() > 0 else np.nan,
    }
    return out


def error_metrics(d):
    r, p = d["r"], d["rhat"]
    q10, q90 = np.quantile(d["sr"], [0.1, 0.9], axis=1)
    q25, q75 = np.quantile(d["sr"], [0.25, 0.75], axis=1)
    return {
        "MAE": float(np.abs(p - r).mean()), "MAE_rw": float(np.abs(r).mean()),
        "RMSE": float(np.sqrt(((p - r) ** 2).mean())), "RMSE_rw": float(np.sqrt((r ** 2).mean())),
        "cov80": float(((r >= q10) & (r <= q90)).mean()), "cov50": float(((r >= q25) & (r <= q75)).mean()),
        "spread_vs_real": float(d["sd"].mean() / r.std()),
    }


def backtest(d, pos, cost="taker", lev=1.0):
    """pos in [-1,1] per decision point, held H bars. Fees only on position changes when trades are contiguous."""
    c = COSTS[cost]
    pos = np.asarray(pos, float) * lev
    prev = np.where(d["contig"], np.r_[0, pos[:-1]], 0.0)
    nxt_contig = np.r_[d["contig"][1:], False]
    fee = c * np.abs(pos - prev) + c * np.abs(pos) * (~nxt_contig)
    gross = pos * d["r"]
    fund = pos * d["fund"]
    net = gross - fee - fund
    return {"gross": gross, "fee": fee, "fund": fund, "net": net, "pos": pos}


def summarize(bt, tf, n_slots_per_year=None):
    net = bt["net"]
    per_year = n_slots_per_year or 365 * 24 * 60 / (HORIZON[tf] * BAR_MIN[tf])
    eq = np.cumprod(1 + net)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    traded = bt["pos"] != 0
    entries = int((bt["fee"] > 0).sum())
    return {
        "mean_net_bp": float(net.mean() * 1e4),
        "total_ret": float(eq[-1] - 1),
        "ann_ret": float(net.mean() * per_year),
        "sharpe": float(net.mean() / net.std() * np.sqrt(per_year)) if net.std() > 0 else 0.0,
        "max_dd": float(dd),
        "exposure": float(traded.mean()),
        "trades": entries,
        "win_rate": float((net[traded] > 0).mean()) if traded.any() else np.nan,
        "gross_sum": float(bt["gross"].sum()), "fee_sum": float(bt["fee"].sum()), "fund_sum": float(bt["fund"].sum()),
    }
