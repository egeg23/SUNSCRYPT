"""Fine-tune the Kronos predictor on Bybit perp candles (tokenizer frozen).

Train: Bybit archive 2022-01 .. 2024-06 (6 pairs, 5m/15m/1h/4h).  Early-stopping: Binance perps 2024-07 .. 2024-12
(part of the validation period; the test period 2025-07+ is never touched).
Fixes vs. the repo scripts: teacher forcing for the s2 head (repo trains s2 on a *sampled* s1), and window
normalisation uses only the context part (finetune_csv uses the whole window, incl. the future).
"""
import argparse, math, os, sys, time
import numpy as np, pandas as pd, torch

sys.path.insert(0, os.path.dirname(__file__))
from fastkronos import load  # noqa: E402
from model.kronos import calc_time_stamps  # noqa: E402

from paths import DATA_DIR, MODEL_DIR, RESULTS_DIR  # noqa: E402
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
TFS = {"5": "5min", "15": "15min", "60": "1h", "240": "4h"}
BIN_TF = {"5": "5m", "15": "15m", "60": "1h", "240": "4h"}
COLS = ["open", "high", "low", "close", "volume", "amount"]


def series(src, sym, tf, a, b):
    if src == "bybit":
        df = pd.read_parquet(f"{DATA_DIR}/bybit/{sym}_{tf}.parquet").astype(float)
    else:
        df = pd.read_parquet(f"{DATA_DIR}/binance/{sym}_{BIN_TF[tf]}.parquet").astype(float)
    df = df.loc[a:b].copy()
    df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
    st = calc_time_stamps(pd.Series(df.index)).values.astype(np.float32)
    # valid window starts: no gaps inside the window
    gap = np.asarray(pd.Series(df.index).diff().iloc[1:] != pd.Timedelta(TFS[tf]))
    return df[COLS].values.astype(np.float32), st, gap


def windows(src, a, b, W):
    out = []
    for sym in SYMBOLS:
        for tf in TFS:
            x, st, gap = series(src, sym, tf, a, b)
            if len(x) <= W:
                continue
            cg = np.r_[0, np.cumsum(gap)]
            starts = np.where(cg[W - 1:] - cg[:len(cg) - W + 1] == 0)[0]
            if len(starts):
                out.append((x, st, starts, tf))
    return out


def make_batch(pool, rng, B, L, W, clip=5.0):
    # sample timeframe uniformly, then a (pair, start); short TFs would otherwise dominate
    xs, ss = [], []
    for _ in range(B):
        x, st, starts, _ = pool[rng.integers(len(pool))]
        s = starts[rng.integers(len(starts))]
        w = x[s:s + W]
        mu, sd = w[:L].mean(0), w[:L].std(0)
        xs.append(np.clip((w - mu) / (sd + 1e-5), -clip, clip)); ss.append(st[s:s + W])
    return torch.tensor(np.stack(xs)), torch.tensor(np.stack(ss))


def loss_on(model, tok, x, st, L):
    with torch.no_grad():
        t0, t1 = tok.encode(x, half=True)
    s1_in, s2_in = t0[:, :-1], t1[:, :-1]
    s1_out, s2_out = t0[:, 1:], t1[:, 1:]
    s1l, s2l = model(s1_in, s2_in, st[:, :-1], use_teacher_forcing=True, s1_targets=s1_out)
    # loss on the forecast part only (positions L-1 .. W-2 predict bars L .. W-1)
    sl = slice(L - 1, None)
    loss, l1, l2 = model.head.compute_loss(s1l[:, sl], s2l[:, sl], s1_out[:, sl], s2_out[:, sl])
    return loss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small")
    ap.add_argument("--steps", type=int, default=1200)
    ap.add_argument("--B", type=int, default=16)
    ap.add_argument("--L", type=int, default=256)
    ap.add_argument("--H", type=int, default=12)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "ft_small"))
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    W = a.L + a.H
    tok, model, _ = load(a.model)
    for p in tok.parameters():
        p.requires_grad_(False)
    train = windows("bybit", "2022-01-01", "2024-06-30 23:59", W)
    val = windows("binance", "2024-07-01", "2024-12-31 23:59", W)
    vrng = np.random.default_rng(123)
    vb = [make_batch(val, vrng, 32, a.L, W) for _ in range(8)]   # fixed 256 validation windows

    def vloss():
        model.eval()
        with torch.no_grad():
            v = float(np.mean([loss_on(model, tok, x, s, a.L).item() for x, s in vb]))
        model.train()
        return v

    best = vloss()
    print(f"step 0 val_loss {best:.4f} (pretrained)", flush=True)
    model.save_pretrained(a.out)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.1, betas=(0.9, 0.95))
    warm = 50
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(s, a.steps) / a.steps)))
    model.train()
    t0, run = time.time(), []
    for step in range(1, a.steps + 1):
        x, s = make_batch(train, rng, a.B, a.L, W)
        loss = loss_on(model, tok, x, s, a.L)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
        opt.step(); sched.step()
        run.append(loss.item())
        if step % 100 == 0:
            v = vloss()
            msg = f"step {step} train {np.mean(run[-100:]):.4f} val_loss {v:.4f} ({time.time() - t0:.0f}s)"
            if v < best:
                best = v
                model.save_pretrained(a.out)
                msg += " *saved"
            print(msg, flush=True)
    print("best val_loss", best)


if __name__ == "__main__":
    main()
