"""'Self-learning' simulation: monthly re-fine-tuning over the test period, no look-ahead.

Before month M: continue fine-tuning the previous checkpoint on Binance perp candles from [M - window_months, M)
(6 pairs, 5m/15m/1h/4h), then forecast all decision points of month M (same global grid as the static test run).
Output: results/preds/roll_test_<sym>_<tf>.npz in the same format as run_preds.py.
"""
import argparse, math, os, sys, time
import numpy as np, pandas as pd, torch

sys.path.insert(0, os.path.dirname(__file__))
from fastkronos import FastKronos, load, prepare  # noqa: E402
from finetune import windows, make_batch, loss_on  # noqa: E402
import run_preds as rp  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def train(model, tok, a, b, steps, lr, B, L, H, seed):
    pool = windows("binance", a, b, L + H)
    rng = np.random.default_rng(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.1, betas=(0.9, 0.95))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * s / steps)))
    model.train()
    losses = []
    for _ in range(steps):
        x, s = make_batch(pool, rng, B, L, L + H)
        loss = loss_on(model, tok, x, s, L)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
        opt.step(); sched.step()
        losses.append(loss.item())
    model.eval()
    return float(np.mean(losses[-20:]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=f"{ROOT}/results/ft_small_s300")
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--first_steps", type=int, default=300)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--window_months", type=int, default=6)
    ap.add_argument("--tfs", default="1h,4h")
    ap.add_argument("--S", type=int, default=16)
    ap.add_argument("--L", type=int, default=256)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--tag", default="roll")
    ap.add_argument("--end", default="2026-09")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    tok, model, ctx = load("small", a.ckpt)
    for p in tok.parameters():
        p.requires_grad_(False)
    months = pd.period_range("2025-07", a.end, freq="M")
    tfs = a.tfs.split(",")
    # global decision grid (identical to the static test run)
    grids = {}
    for tf in tfs:
        for sym in rp.SYMBOLS:
            df = rp.load_bars(sym, tf)
            grids[sym, tf] = (df, rp.decision_index(df, tf, "test", a.L, 0))
    store = {k: {"samples": [], "idx": []} for k in grids}
    for k, m in enumerate(months):
        start = m.start_time
        lo = (m - a.window_months).start_time
        t0 = time.time()
        steps = a.first_steps if k == 0 else a.steps
        loss = train(model, tok, str(lo), str(start - pd.Timedelta(minutes=1)), steps, a.lr, 16, a.L, 12, seed=k)
        fk = FastKronos(tok, model, ctx)
        n = 0
        for (sym, tf), (df, idx) in grids.items():
            H = rp.HORIZON[tf]
            bar = pd.Timedelta(rp.FREQ[tf])
            sel = idx[(df.index[idx] + bar >= start) & (df.index[idx] + bar < (m + 1).start_time)]
            torch.manual_seed(hash((sym, tf, str(m))) % 2**31)
            for j in range(0, len(sel), 8):
                chunk = sel[j:j + 8]
                X, XS, YS, MU, SD = [], [], [], [], []
                for i in chunk:
                    w = df.iloc[i - a.L + 1:i + 1]
                    fut = pd.date_range(df.index[i] + bar, periods=H, freq=bar)
                    xn, xs, ys, mu, sd = prepare(w, w.index, fut)
                    X.append(xn); XS.append(xs); YS.append(ys); MU.append(mu); SD.append(sd)
                with torch.no_grad():
                    z = fk.generate(np.stack(X), np.stack(XS), np.stack(YS), H, S=a.S)
                close = z[..., 3] * (np.stack(SD)[:, None, None, 3] + 1e-5) + np.stack(MU)[:, None, None, 3]
                store[sym, tf]["samples"].append(close); store[sym, tf]["idx"].append(chunk)
            n += len(sel)
        print(f"{m}: trained {steps} steps on {lo.date()}..{start.date()} loss {loss:.4f}; {n} forecasts; {time.time() - t0:.0f}s",
              flush=True)
        model.save_pretrained(f"{ROOT}/results/roll_ckpt")
    if a.end != "2026-09":
        print("partial run, not saved"); return
    for (sym, tf), (df, idx) in grids.items():
        smp = np.concatenate(store[sym, tf]["samples"]); ii = np.concatenate(store[sym, tf]["idx"])
        assert np.array_equal(ii, idx), (sym, tf)
        vals = df.values.astype(np.float32)
        H = rp.HORIZON[tf]
        np.savez_compressed(f"{ROOT}/results/preds/{a.tag}_test_{sym}_{tf}.npz",
                            t=df.index[idx].values.astype("datetime64[m]").astype("int64"), close=vals[idx, 3],
                            samples=smp, fut_close=np.stack([vals[i + 1:i + 1 + H, 3] for i in idx]), idx=idx)
    print("done")


if __name__ == "__main__":
    main()
