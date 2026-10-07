"""Контролируемое дообучение и контроль дрейфа модели Kronos (бриф, этап 8).

    python -m sunscrypt_engine.models_job retrain   # раз в неделю (cron)
    python -m sunscrypt_engine.models_job drift     # раз в сутки (cron)

Дообучение. Сегодня T (00:00 UTC). Претендент — чемпион, дообученный на
свечах [T−56−365 дн, T−56 дн) пар, которые торгуются по Kronos; лучший шаг
выбирается по [T−56, T−28). Последние 4 недели [T−28, T) претендент не видел
— на них после комиссий сравниваются чемпион, претендент и простые базы
(моментум, «не торговать»). Выпуск — только если претендент лучше всех
(evalkit.decide); иначе остаётся чемпион. Каждое решение с причиной и
цифрами — в базе (model_events), видно в админке.

Дрейф. Живые сигналы чемпиона (поток signals в Redis) пересчитываются в
результат каждого 8-часового окна после комиссии и сравниваются с ожиданием
из проверки чемпиона на истории (evalkit.drift). Дрейф → откат на прошлого
чемпиона, а если его нет — пауза Kronos (сигналы «вне рынка»).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pandas as pd
import redis

from sunscrypt_engine import evalkit, keys, registry
from sunscrypt_engine import pairs as pairs_cfg

log = logging.getLogger("models")

BYBIT = "https://api.bybit.com"
HOLDOUT_D, VAL_D, TRAIN_D = 28, 28, 365
CONTEXT, H, S, BATCH = 256, 8, 16, 4  # пачка 4 точки × 16 сценариев: ~1 ГБ (32 — 6 ГБ)
COLS = ["open", "high", "low", "close", "volume", "amount"]


# ── данные ─────────────────────────────────────────────────────────────────
def _get(c: httpx.Client, path: str, params: dict) -> dict:
    for attempt in range(5):
        r = c.get(f"{BYBIT}{path}", params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") == 0:
            return data["result"]
        if attempt == 4:
            raise RuntimeError(f"Bybit {path}: {data.get('retMsg')}")
        time.sleep(2 + attempt * 3)  # лимит частоты — ждём
    raise AssertionError


def klines_range(c: httpx.Client, sym: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Часовые свечи [start, end), только закрытые; индекс — время открытия."""
    rows: list = []
    cur = int(end.value // 1_000_000) - 1
    lo = int(start.value // 1_000_000)
    while cur >= lo:
        res = _get(c, "/v5/market/kline", {"category": "linear", "symbol": sym, "interval": "60",
                                           "start": lo, "end": cur, "limit": 1000})
        page = res["list"]  # новые сначала
        if not page:
            break
        rows += page
        cur = int(page[-1][0]) - 1
        time.sleep(0.3)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "amount"]).astype(float)
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    now = pd.Timestamp(time.time(), unit="s")
    return df[(df.index >= start) & (df.index + pd.Timedelta(hours=1) <= min(end, now))][COLS]


def funding_range(c: httpx.Client, sym: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Ставки фандинга по времени начисления."""
    out: dict = {}
    cur = int(end.value // 1_000_000)
    lo = int(start.value // 1_000_000)
    while cur > lo:
        res = _get(c, "/v5/market/funding/history", {"category": "linear", "symbol": sym,
                                                     "startTime": lo, "endTime": cur, "limit": 200})
        page = res["list"]
        if not page:
            break
        for x in page:
            out[pd.Timestamp(int(x["fundingRateTimestamp"]), unit="ms")] = float(x["fundingRate"])
        cur = min(int(x["fundingRateTimestamp"]) for x in page) - 1
        time.sleep(0.3)
    return pd.Series(out, dtype=float).sort_index()


def load_data(pairs: list[str], start: pd.Timestamp, end: pd.Timestamp, fund_from: pd.Timestamp) -> dict:
    data = {}
    with httpx.Client(timeout=30) as c:
        for sym in pairs:
            df = klines_range(c, sym, start, end)
            df["funding"] = funding_range(c, sym, fund_from, end).reindex(df.index)
            data[sym] = df
            log.info("%s: свечей %d (%s … %s)", sym, len(df), df.index[0], df.index[-1])
    return data


# ── модель ─────────────────────────────────────────────────────────────────
def forecaster(model_path: str, threads: int):
    import torch

    from sunscrypt_engine.fastkronos import FastKronos, load

    torch.set_num_threads(threads)
    tok, m, ctx = load("small", model_path)
    return FastKronos(tok, m, ctx)


def predict(fk, df: pd.DataFrame, since: pd.Timestamp, until: pd.Timestamp) -> pd.Series:
    """Прогноз rhat во всех решающих точках (закрытия 00/08/16 UTC) на [since, until]."""
    from sunscrypt_engine.fastkronos import prepare

    bar = pd.Timedelta(hours=1)
    close = df.index + bar
    pts = [i for i in np.flatnonzero((close.hour % H == 0) & (close >= since) & (close <= until))
           if i >= CONTEXT - 1]
    out = {}
    for b in range(0, len(pts), BATCH):
        chunk = pts[b : b + BATCH]
        xs, xss, yss, mus, sds = [], [], [], [], []
        for i in chunk:
            w = df.iloc[i - CONTEXT + 1 : i + 1][COLS]
            fut = pd.date_range(w.index[-1] + bar, periods=H, freq=bar)
            xn, x_s, y_s, mu, sd = prepare(w, w.index, fut)
            xs.append(xn), xss.append(x_s), yss.append(y_s), mus.append(mu), sds.append(sd)
        z = fk.generate(np.stack(xs), np.stack(xss), np.stack(yss), H, S=S)
        for k, i in enumerate(chunk):
            c = z[k, :, -1, 3] * (sds[k][3] + 1e-5) + mus[k][3]
            out[df.index[i] + bar] = float((c / df["close"].iloc[i] - 1).mean())
    return pd.Series(out, dtype=float).sort_index()


def finetune(base: str, data: dict, train: tuple, val: tuple, out: str, steps: int, threads: int,
             micro: int = 4) -> dict:
    """Дообучение от чемпиона (токенизатор заморожен, как в исследовании:
    engine/sunscrypt_engine/finetune.py). Сохраняется лучший шаг по val."""
    import math

    import torch

    sys.path.insert(0, os.path.dirname(__file__))
    import finetune as ft  # noqa: E402 — модуль исследования, импорт по пути
    from model.kronos import calc_time_stamps  # noqa: E402

    from sunscrypt_engine.fastkronos import load

    torch.set_num_threads(threads)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    L, W = CONTEXT, CONTEXT + H

    def pool(a, b):
        res = []
        for df in data.values():
            d = df.loc[a:b]
            if len(d) <= W:
                continue
            st = calc_time_stamps(pd.Series(d.index)).values.astype(np.float32)
            gap = np.asarray(pd.Series(d.index).diff().iloc[1:] != pd.Timedelta(hours=1))
            cg = np.r_[0, np.cumsum(gap)]
            starts = np.where(cg[W - 1 :] - cg[: len(cg) - W + 1] == 0)[0]
            if len(starts):
                res.append((d[COLS].values.astype(np.float32), st, starts, "60"))
        return res

    tr, va = pool(*train), pool(*val)
    tok, model, _ = load("small", base)
    for p in tok.parameters():
        p.requires_grad_(False)
    vrng = np.random.default_rng(123)
    vb = [ft.make_batch(va, vrng, 8, L, W) for _ in range(16)]  # 128 окон, малыми порциями

    def vloss() -> float:
        model.eval()
        with torch.no_grad():
            v = float(np.mean([ft.loss_on(model, tok, x, s, L).item() for x, s in vb]))
        model.train()
        return v

    best = start = vloss()
    model.save_pretrained(out)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=0.1, betas=(0.9, 0.95))
    warm = 20
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(s, steps) / steps)))
    model.train()
    t0 = time.time()
    for step in range(1, steps + 1):
        # Пачка 16 окон — частями по micro: память (потолок контейнера 2 ГБ;
        # целиком 16 окон занимали больше), результат тот же.
        opt.zero_grad()
        for _ in range(16 // micro):
            x, s = ft.make_batch(tr, rng, micro, L, W)
            (ft.loss_on(model, tok, x, s, L) * (micro / 16)).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
        opt.step()
        sched.step()
        if step % 25 == 0 or step == steps:
            v = vloss()
            if v < best:
                best = v
                model.save_pretrained(out)
            log.info("шаг %d: val %.4f (лучший %.4f), %.0f с", step, v, best, time.time() - t0)
    return {"val_loss_start": start, "val_loss_best": best, "steps": steps}


def evaluate(paths: dict[str, str], data: dict, holdout: tuple, threads: int) -> dict:
    """После комиссий на окне, которого претендент не видел: модели и база."""
    since = holdout[0] - pd.Timedelta(days=11)  # 30+ прошлых прогнозов для z
    res: dict = {"momentum": {s: evalkit.backtest(df, evalkit.targets_momentum(df), holdout)
                              for s, df in data.items()}}
    for name, path in paths.items():
        fk, res[name] = forecaster(path, threads), {}
        for sym, df in data.items():
            rh = predict(fk, df, since, holdout[1])
            res[name][sym] = evalkit.backtest(df, evalkit.targets_kronos(rh), holdout)
            log.info("%s %s: %+.2f%%", name, sym, res[name][sym]["net"] * 100)
    return res


def expectation(rows: dict) -> dict:
    """Ожидание для контроля дрейфа: результат одного окна решения по одной паре."""
    return {
        "mean": float(np.mean([r["per_window_mean"] for r in rows.values()])),
        "sd": float(np.mean([r["per_window_sd"] for r in rows.values()])),
    }


# ── журнал ─────────────────────────────────────────────────────────────────
async def _record(version: str, action: str, champion: str, reason: str, metrics: dict | None = None) -> None:
    from app.db import SessionLocal
    from app.models import EngineEvent, ModelEvent

    async with SessionLocal() as db:
        db.add(ModelEvent(version=version, action=action, champion=champion, reason=reason[:1000],
                          metrics=metrics or {}))
        if action in ("rolled_back", "paused"):
            db.add(EngineEvent(kind="alarm", message=f"Модель: {reason}"[:500]))
        await db.commit()


async def _events() -> list:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ModelEvent

    async with SessionLocal() as db:
        return list(await db.scalars(select(ModelEvent).order_by(ModelEvent.id)))


def record(*a, **kw) -> None:
    asyncio.run(_record(*a, **kw))
    log.info("журнал: %s %s", a[1], a[3])


def ensure_baseline() -> None:
    if not asyncio.run(_events()):
        record(registry.BASE, "baseline", registry.BASE,
               "Исходная модель: Kronos-small, дообученная в исследовании на свечах Bybit 2022-01…2024-06.")


def kronos_pairs() -> list[str]:
    return [p["sym"] for p in pairs_cfg.load()["pairs"] if p["strategy"] == "kronos_1h"]


# ── задачи ─────────────────────────────────────────────────────────────────
def retrain(steps: int, threads: int, today: pd.Timestamp | None = None) -> None:
    ensure_baseline()
    champ = registry.champion()
    pairs = kronos_pairs()
    if not pairs:
        record(champ, "skipped", champ, "Ни одна пара не торгуется по Kronos — дообучение не нужно.")
        return
    T = today or pd.Timestamp(datetime.now(UTC).date())
    h0, v0 = T - timedelta(days=HOLDOUT_D), T - timedelta(days=HOLDOUT_D + VAL_D)
    t0 = v0 - timedelta(days=TRAIN_D)
    data = load_data(pairs, t0 - timedelta(hours=CONTEXT + 24), T, h0 - timedelta(days=1))
    version = f"ft-{T:%Y%m%d}"
    tmp = os.path.join(registry.reg_dir(), f".train-{version}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        fit = finetune(registry.path_of(champ), data, (t0, v0 - timedelta(hours=1)),
                       (v0, h0 - timedelta(hours=1)), tmp, steps, threads)
        holdout = (h0, T - timedelta(hours=1))
        ev = evaluate({"champion": registry.path_of(champ), "challenger": tmp}, data, holdout, threads)
        ok, reason = evalkit.decide(evalkit.mean_of(ev["champion"]), evalkit.mean_of(ev["challenger"]),
                                    evalkit.mean_of(ev["momentum"]))
        metrics = {
            "parent": champ, "pairs": pairs, "fit": fit,
            "periods": {"train": [str(t0), str(v0)], "val": [str(v0), str(h0)], "holdout": [str(h0), str(T)]},
            "net": {k: evalkit.mean_of(v) for k, v in ev.items()},
            "by_pair": {k: {s: {f: r[f] for f in ("net", "sharpe", "trades")} for s, r in v.items()}
                        for k, v in ev.items()},
            # Ожидание для контроля дрейфа — у того, кто останется чемпионом.
            "expect": expectation(ev["challenger" if ok else "champion"]),
        }
        if ok:
            final = registry.path_of(version)
            shutil.rmtree(final, ignore_errors=True)
            os.replace(tmp, final)
            registry.set_champion(version)
            _redis().delete(keys.PAUSE_KRONOS)
            record(version, "released", version, reason, metrics)
        else:
            record(version, "rejected", champ, reason, metrics)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def live_windows(r: redis.Redis, version: str, since_ms: int) -> list[float]:
    """Результат каждого 8-часового окна живых сигналов модели после комиссии."""
    by: dict[str, list[dict]] = {}
    for _id, f in r.xrange(keys.SIGNAL_STREAM, min=f"{since_ms}-0"):
        s = json.loads(f[b"json"])
        if s.get("model") == version and not s.get("paused"):
            by.setdefault(s["sym"], []).append(s)
    out = []
    for sigs in by.values():
        sigs.sort(key=lambda s: s["ts_close"])
        prev_target = 0
        for a, b in zip(sigs, sigs[1:], strict=False):
            if b["ts_close"] - a["ts_close"] != H * 3_600_000:
                prev_target = 0
                continue
            out.append(a["target"] * (b["close"] / a["close"] - 1)
                       - evalkit.TAKER * abs(a["target"] - prev_target))
            prev_target = a["target"]
    return out


def _redis() -> redis.Redis:
    return redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def check_drift(r: redis.Redis | None = None) -> str:
    ensure_baseline()
    r = r or _redis()
    champ = registry.champion()
    if r.get(keys.PAUSE_KRONOS):
        return "Kronos на паузе — проверять нечего"
    events = asyncio.run(_events())
    mine = [e for e in events if e.champion == champ and (e.metrics or {}).get("expect")]
    if not mine:
        return f"Нет ожидания для {champ}: появится после первой проверки дообучением"
    exp = mine[-1].metrics["expect"]
    became = [e for e in events if e.champion == champ and e.action in ("baseline", "released", "rolled_back",
                                                                       "resumed")]
    since = (became[-1] if became else mine[-1]).ts
    live = live_windows(r, champ, int(since.timestamp() * 1000))
    bad, text = evalkit.drift(live, exp["mean"], exp["sd"])
    if not bad:
        return text
    parent = next((e.metrics.get("parent") for e in reversed(events)
                   if e.action == "released" and e.version == champ), None)
    if parent and os.path.isdir(registry.path_of(parent)):
        registry.set_champion(parent)
        record(champ, "rolled_back", parent, f"{text}. Откат на {parent}.", {"live": len(live)})
    else:
        r.set(keys.PAUSE_KRONOS, text)
        record(champ, "paused", champ, f"{text}. Прошлой версии нет — пауза Kronos.", {"live": len(live)})
    return text


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["retrain", "drift"])
    ap.add_argument("--steps", type=int, default=int(os.environ.get("RETRAIN_STEPS", "150")))
    ap.add_argument("--threads", type=int, default=int(os.environ.get("RETRAIN_THREADS", "2")))
    a = ap.parse_args()
    if a.job == "retrain":
        try:
            retrain(a.steps, a.threads)
        except Exception as e:
            champ = registry.champion()
            record(champ, "failed", champ, f"Дообучение не завершилось: {type(e).__name__}: {e}"[:500])
            raise
    else:
        print(check_drift())


if __name__ == "__main__":
    main()
