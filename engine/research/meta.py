"""Meta-labeling: learn from the outcomes of our own past Kronos signals which ones to take.

Primary signal: sign(z) of the fine-tuned Kronos (debiased).  Label: the trade in that direction made money after a
taker round trip.  Features use only data known at decision time.  Two variants:
  static  - fit once on the validation period (2024-07..2025-06), apply to the whole test period;
  rolling - "self-learning": refit every month on all signals whose outcome is already known.
Trade only when P(profit) > 0.5.
"""
import os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(__file__))
from evaluate import load, SYMBOLS, HORIZON, BAR_MIN, COSTS, backtest, summarize  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
RT = 2 * COSTS["taker"]


def features(d, sym, tf):
    df = pd.read_parquet(f"{ROOT}/data/binance/{sym}_{tf}.parquet")
    c, v = df.close.values, df.volume.values
    lr = np.r_[0, np.diff(np.log(c))]
    idx, H = d["idx"], HORIZON[tf]
    vol24 = np.array([lr[i - 23:i + 1].std() for i in idx])
    vol96 = np.array([lr[i - 95:i + 1].std() for i in idx])
    trend = np.array([c[i] / c[i - 96:i + 1].mean() - 1 for i in idx])
    vz = np.array([(np.log1p(v[i - 7:i + 1].mean()) - np.log1p(v[i - 255:i + 1]).mean()) for i in idx])
    f = pd.read_parquet(f"{ROOT}/data/binance/{sym}_funding.parquet")
    ft, fr = f.calc_time.values // 60000, f.rate.values
    fund = fr[np.clip(np.searchsorted(ft, d["t"] + BAR_MIN[tf], "right") - 1, 0, len(fr) - 1)]
    hour = pd.to_datetime(d["t"], unit="m").hour.values
    side = np.sign(d["z"]); side[side == 0] = 1
    X = np.c_[np.abs(d["z"]), side * d["rhat"] / (d["sd"] + 1e-9), np.abs(2 * d["pup"] - 1), d["sd"] / (vol24 * np.sqrt(H) + 1e-9),
              vol24, vol96 / (vol24 + 1e-9), side * trend, side * d["past"], vz, side * fund,
              np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24), side]
    y = (side * d["r"] - RT - side * d["fund"] > 0).astype(int)
    return X, y, side


def build(tag, period, tf):
    rows = []
    for s in SYMBOLS:
        d = load(tag, period, s, tf)
        X, y, side = features(d, s, tf)
        rows.append((s, d, X, y, side))
    return rows


def models():
    return {"logit": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
            "lgbm": lambda: lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=8, min_child_samples=50,
                                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)}


def run(tf, tag="ft300"):
    val, test = build(tag, "val", tf), build(tag, "test", tf)
    Xv = np.concatenate([r[2] for r in val]); yv = np.concatenate([r[3] for r in val])
    Tv = np.concatenate([r[1]["t"] for r in val])
    out = {}
    for name, mk in models().items():
        # static
        m = mk().fit(Xv, yv)
        pos_s = {s: side * (m.predict_proba(X)[:, 1] > 0.5) for s, d, X, y, side in test}
        # rolling monthly refit on all outcomes already realised (expanding window)
        Xall = np.concatenate([r[2] for r in test]); yall = np.concatenate([r[3] for r in test])
        tall = np.concatenate([r[1]["t"] for r in test])
        tend = tall + (HORIZON[tf] + 1) * BAR_MIN[tf]          # when the outcome becomes known
        months = pd.period_range("2025-07", "2026-09", freq="M")
        prob = np.zeros(len(tall))
        for mth in months:
            a = int(mth.start_time.value // 60_000_000_000); b = int((mth + 1).start_time.value // 60_000_000_000)
            known = tend <= a
            X_tr = np.r_[Xv, Xall[known]]; y_tr = np.r_[yv, yall[known]]
            mm = mk().fit(X_tr, y_tr)
            sel = (tall >= a) & (tall < b)
            if sel.any():
                prob[sel] = mm.predict_proba(Xall[sel])[:, 1]
        pos_r, k = {}, 0
        for s, d, X, y, side in test:
            pos_r[s] = side * (prob[k:k + len(y)] > 0.5); k += len(y)
        out[name] = (pos_s, pos_r)
    res = []
    base = {s: np.sign(d["z"]) * (np.abs(d["z"]) > 1.0) for s, d, X, y, side in test}
    allin = {s: side for s, d, X, y, side in test}
    variants = [("sign(z), every signal", allin), ("|z|>1 (pre-registered rule)", base)]
    for name, (ps, pr) in out.items():
        variants += [(f"meta {name}, static", ps), (f"meta {name}, monthly refit", pr)]
    for label, P in variants:
        for cost in ["taker", "maker"]:
            bts = {s: backtest(d, P[s], cost) for s, d, X, y, side in test}
            agg = {k2: np.mean([b[k2] for b in bts.values()], 0) for k2 in ["gross", "fee", "fund", "net"]}
            agg["pos"] = np.mean([np.abs(b["pos"]) for b in bts.values()], 0)
            sm = summarize(agg, tf)
            sm["trades"] = int(sum((b["fee"] > 0).sum() for b in bts.values()))
            res.append(dict(tf=tf, variant=label, cost=cost, sharpe=sm["sharpe"], total_ret=sm["total_ret"],
                            max_dd=sm["max_dd"], trades=sm["trades"], exposure=sm["exposure"]))
    # label base rate for context
    print(tf, "val share profitable", yv.mean().round(3), "test", np.concatenate([r[3] for r in test]).mean().round(3))
    return pd.DataFrame(res)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    r = pd.concat([run("1h"), run("4h")])
    r.to_csv(f"{ROOT}/results/tables/meta_test.csv", index=False)
    print(r.round(3).to_string())
