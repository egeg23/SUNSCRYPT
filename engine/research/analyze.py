"""Tables: forecast quality vs baselines and cost-aware backtests, per timeframe, pooled over 6 pairs."""
import argparse, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(__file__))
from evaluate import (SYMBOLS, HORIZON, BAR_MIN, COSTS, load, forecast_metrics, error_metrics,  # noqa: E402
                      backtest, summarize)

TFS = ["5m", "15m", "1h", "4h"]


def load_all(tag, period, tf):
    ds = {s: load(tag, period, s, tf) for s in SYMBOLS}
    return {s: d for s, d in ds.items() if d is not None}


def forecast_table(tag, period):
    rows = []
    rng = np.random.default_rng(0)
    for tf in TFS:
        ds = load_all(tag, period, tf)
        if not ds:
            continue
        for s, d in list(ds.items()) + [("ALL", None)]:
            if d is None:      # pooled over pairs
                d = {k: np.concatenate([x[k] for x in ds.values()]) for k in ["r", "rhat", "past", "sr", "sd", "z"]}
            preds = {"kronos": d["rhat"], "kronos_db": d["z"], "momentum": d["past"], "mean_rev": -d["past"],
                     "random": rng.standard_normal(len(d["r"]))}
            for name, p in preds.items():
                m = forecast_metrics(d, p)
                m.update(tf=tf, symbol=s, model=name)
                if name == "kronos":
                    m.update(error_metrics(d))
                rows.append(m)
        # cross-sectional RankIC across the 6 pairs at each decision time
        t = ds[SYMBOLS[0]]["t"]
        if all(np.array_equal(t, x["t"]) for x in ds.values()) and len(ds) == 6:
            R = np.stack([x["r"] for x in ds.values()], 1)
            for name, P in [("kronos", np.stack([x["rhat"] for x in ds.values()], 1)),
                            ("momentum", np.stack([x["past"] for x in ds.values()], 1))]:
                cs = [spearmanr(P[i], R[i]).correlation for i in range(len(R)) if P[i].std() > 0 and R[i].std() > 0]
                rows.append(dict(tf=tf, symbol="XS", model=name, n=len(cs), RankIC=float(np.nanmean(cs)),
                                 IC_t=float(np.nanmean(cs) / (np.nanstd(cs) + 1e-12) * np.sqrt(len(cs)))))
    return pd.DataFrame(rows)


def policy_pos(d, kind, q=0.5, k=0.0, cost="taker"):
    c2 = 2 * COSTS["taker"]
    if kind == "kronos":
        long = (d["pup"] >= q) & (d["rhat"] > k * c2)
        short = (d["pup"] <= 1 - q) & (d["rhat"] < -k * c2)
        if q <= 0.5 and k == 0:
            return np.sign(d["rhat"])
        return long.astype(float) - short.astype(float)
    if kind == "kronos_size":     # size proportional to agreement
        conf = np.clip((np.abs(2 * d["pup"] - 1) - (2 * q - 1)) / (1 - (2 * q - 1) + 1e-9), 0, 1)
        ok = np.abs(d["rhat"]) > k * c2
        return np.sign(d["rhat"]) * conf * ok
    if kind == "kronos_db":       # debiased: trade the z-score of rhat vs its trailing mean
        return np.sign(d["z"]) * (np.abs(d["z"]) > k)
    if kind == "momentum":
        return np.sign(d["past"])
    if kind == "mean_rev":
        return -np.sign(d["past"])
    if kind == "buy_hold":
        return np.ones(len(d["r"]))
    if kind == "random":
        return np.random.default_rng(1).choice([-1.0, 1.0], len(d["r"]))
    raise ValueError(kind)


def portfolio(ds, kind, cost, lev=1.0, **kw):
    """Equal-weight over pairs (1/6 of capital each)."""
    if kind == "buy_hold":     # one entry, one exit for the whole period
        ds = {s: dict(d, contig=np.r_[False, np.ones(len(d["r"]) - 1, bool)]) for s, d in ds.items()}
    bts = {s: backtest(d, policy_pos(d, kind, cost=cost, **kw), cost, lev) for s, d in ds.items()}
    agg = {k: np.mean([b[k] for b in bts.values()], 0) for k in ["gross", "fee", "fund", "net"]}
    agg["pos"] = np.mean([np.abs(b["pos"]) for b in bts.values()], 0)
    return agg, bts


def xs_longshort(ds, cost, signal="rhat", n=2):
    """Market-neutral: long the n pairs with the highest forecast, short the n lowest; 1/(2n) of capital each."""
    syms = list(ds)
    S = np.stack([ds[s][signal] for s in syms], 1)
    rk = S.argsort(1).argsort(1)
    W = np.where(rk >= len(syms) - n, 1.0, np.where(rk < n, -1.0, 0.0)) / (2 * n)
    bts = {s: backtest(ds[s], W[:, j] * len(syms), cost) for j, s in enumerate(syms)}   # backtest is per 1/6 sleeve
    agg = {k: np.mean([b[k] for b in bts.values()], 0) for k in ["gross", "fee", "fund", "net"]}
    agg["pos"] = np.mean([np.abs(b["pos"]) for b in bts.values()], 0)
    return agg, bts


def strategy_table(tag, period, grid=None, cost="taker"):
    rows = []
    for tf in TFS:
        ds = load_all(tag, period, tf)
        if len(ds) < 6:
            continue
        variants = [("kronos", dict()), ("momentum", {}), ("mean_rev", {}), ("buy_hold", {}), ("random", {})]
        variants += grid or []
        variants += [("xs_ls", dict(signal="rhat")), ("xs_ls", dict(signal="past"))]
        for kind, kw in variants:
            agg, bts = xs_longshort(ds, cost, **kw) if kind == "xs_ls" else portfolio(ds, kind, cost, **kw)
            m = summarize(agg, tf)
            # trades / win rate counted per pair
            m["trades"] = int(sum((b["fee"] > 0).sum() for b in bts.values()))
            tr = np.concatenate([b["net"][b["pos"] != 0] for b in bts.values()])
            m["win_rate"] = float((tr > 0).mean()) if len(tr) else np.nan
            m["fee_share"] = float(agg["fee"].sum() / max(abs(agg["gross"].sum()), 1e-12))
            m.update(tf=tf, strategy=kind + ("" if not kw else " " + json.dumps(kw)), cost=cost)
            rows.append(m)
    return pd.DataFrame(rows)


GRID = [("kronos", dict(q=q, k=k)) for q in [0.5, 0.6, 0.7, 0.8] for k in [0, 1, 2] if not (q == 0.5 and k == 0)] + \
       [("kronos_size", dict(q=q, k=k)) for q in [0.5, 0.6] for k in [0, 1]] + \
       [("kronos_db", dict(k=k)) for k in [0, 0.5, 1.0, 1.5]]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="small")
    ap.add_argument("--period", default="val")
    ap.add_argument("--grid", type=int, default=0)
    a = ap.parse_args()
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    f = forecast_table(a.tag, a.period)
    os.makedirs("results/tables", exist_ok=True)
    f.to_csv(f"results/tables/forecast_{a.tag}_{a.period}.csv", index=False)
    print(f[f.symbol.isin(["ALL", "XS"])].round(4).to_string())
    for cost in ["taker", "maker", "zero"]:
        s = strategy_table(a.tag, a.period, GRID if a.grid else None, cost)
        s.to_csv(f"results/tables/strategy_{a.tag}_{a.period}_{cost}.csv", index=False)
        print(cost)
        print(s[["tf", "strategy", "sharpe", "ann_ret", "total_ret", "max_dd", "mean_net_bp", "trades", "win_rate",
                 "exposure", "fee_share"]].round(3).to_string())
