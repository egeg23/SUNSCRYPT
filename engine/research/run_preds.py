"""Walk-forward Kronos forecasts on out-of-sample periods (after the June-2024 pretraining cutoff).

At each decision bar t (bar t is closed) the model sees bars [t-L+1 .. t] only, normalised with stats of that
window only, and samples S paths of H future bars. Decision bars are spaced H apart (non-overlapping trades).
Saves samples + realised future closes to results/preds/<tag>_<period>_<sym>_<tf>.npz
"""
import argparse, os, sys, time
import numpy as np, pandas as pd, torch

sys.path.insert(0, os.path.dirname(__file__))
from fastkronos import load, FastKronos, prepare  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
HORIZON = {"5m": 12, "15m": 8, "1h": 8, "4h": 6}
FREQ = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
PERIODS = {"val": ("2024-07-01", "2025-07-01"), "test": ("2025-07-01", "2026-10-01")}
ROOT = os.path.join(os.path.dirname(__file__), "..")


def load_bars(sym, tf):
    df = pd.read_parquet(f"{ROOT}/data/binance/{sym}_{tf}.parquet").astype(float)
    df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
    return df


def decision_index(df, tf, period, L, cap):
    H = HORIZON[tf]
    a, b = (pd.Timestamp(x) for x in PERIODS[period])
    bar = pd.Timedelta(FREQ[tf])
    close_time = df.index + bar                      # a bar is known once it closes
    ok = np.where((close_time >= a) & (close_time + H * bar <= b))[0]
    ok = ok[ok >= L - 1]
    grid = ok[::H]                                   # non-overlapping holding windows
    if cap and len(grid) > cap:
        grid = grid[np.linspace(0, len(grid) - 1, cap).round().astype(int)]
    return grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small")
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--s2fix", type=int, default=0)
    ap.add_argument("--period", default="val")
    ap.add_argument("--tfs", default="1h,4h,15m,5m")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--cap", type=int, default=500)
    ap.add_argument("--S", type=int, default=16)
    ap.add_argument("--L", type=int, default=256)
    ap.add_argument("--T", type=float, default=1.0)
    ap.add_argument("--top_p", type=float, default=0.9)
    ap.add_argument("--P", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--tok", default=None)
    ap.add_argument("--after", default=None)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    tok, model, ctx = load(a.model, a.ckpt, a.tok)
    fk = FastKronos(tok, model, ctx, s2_fix=bool(a.s2fix))
    os.makedirs(f"{ROOT}/results/preds", exist_ok=True)
    for tf in a.tfs.split(","):
        H = HORIZON[tf]
        for sym in a.symbols.split(","):
            out = f"{ROOT}/results/preds/{a.tag}_{a.period}_{sym}_{tf}.npz"
            if os.path.exists(out):
                continue
            torch.manual_seed(hash((sym, tf)) % 2**31)
            df = load_bars(sym, tf)
            idx = decision_index(df, tf, a.period, a.L, a.cap)
            if a.after:
                idx = idx[df.index[idx] >= pd.Timestamp(a.after)]
            bar = pd.Timedelta(FREQ[tf])
            vals = df.values.astype(np.float32)   # open high low close volume amount
            samples = np.empty((len(idx), a.S, H), np.float32)
            t0 = time.time()
            for j in range(0, len(idx), a.P):
                chunk = idx[j:j + a.P]
                X, XS, YS, MU, SD = [], [], [], [], []
                for i in chunk:
                    w = df.iloc[i - a.L + 1:i + 1]
                    fut = pd.date_range(df.index[i] + bar, periods=H, freq=bar)
                    xn, xs, ys, mu, sd = prepare(w, w.index, fut)
                    X.append(xn); XS.append(xs); YS.append(ys); MU.append(mu); SD.append(sd)
                z = fk.generate(np.stack(X), np.stack(XS), np.stack(YS), H, S=a.S, T=a.T, top_p=a.top_p)
                close = z[..., 3] * (np.stack(SD)[:, None, None, 3] + 1e-5) + np.stack(MU)[:, None, None, 3]
                samples[j:j + len(chunk)] = close
            fut_close = np.stack([vals[i + 1:i + 1 + H, 3] for i in idx])
            np.savez_compressed(out, t=df.index[idx].values.astype("datetime64[m]").astype("int64"),
                                close=vals[idx, 3], samples=samples, fut_close=fut_close, idx=idx)
            print(f"{a.tag} {a.period} {sym} {tf}: {len(idx)} pts in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
