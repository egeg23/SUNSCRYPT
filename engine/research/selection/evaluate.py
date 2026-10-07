"""Оценка стратегий и отбор пар по правилам RULES.md (зафиксированы до
расчётов). Пишет отчёт и конфиг пар.

    python research/selection/evaluate.py [--partial]

--partial — посчитать по тем парам, где прогнозы Kronos уже готовы (для
проверки кода; итоговый отбор — только без этого флага).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "..", "var", "data", "selection")
VAL = ("2024-07-01", "2025-06-30 23:59")
TEST = ("2025-07-01", "2026-09-30 23:59")
TAKER, MAKER = 0.00075, 0.0002
H, Z_WINDOW, Z_MIN, Z_THR = 8, 30, 10, 1.0
RULE = {"val_sharpe": 0.5, "val_net": 0.0, "val_trades": 20, "max_pairs": 10}


def hourly_returns(df: pd.DataFrame) -> pd.Series:
    """Доходность свечи i (индекс — время открытия)."""
    return df["close"].pct_change().fillna(0.0)


def targets_kronos(preds: pd.DataFrame) -> pd.Series:
    """Решение во время закрытия решающей свечи: ±1 при |z| > 1 (как в сервисе)."""
    rh = preds["rhat"].to_numpy()
    out = np.zeros(len(rh))
    for i in range(len(rh)):
        hist = rh[max(0, i - Z_WINDOW) : i]
        if len(hist) < Z_MIN:
            continue
        sd = hist.std(ddof=1)
        z = (rh[i] - hist.mean()) / sd if sd > 0 else 0.0
        out[i] = np.sign(z) if abs(z) > Z_THR else 0.0
    return pd.Series(out, index=preds.index)


def targets_momentum(df: pd.DataFrame) -> pd.Series:
    """Раз в сутки (00:00 UTC): знак доходности за последние 6 свечей по 4h = 24h."""
    close_at = df["close"].copy()
    close_at.index = close_at.index + pd.Timedelta(hours=1)  # время закрытия
    days = close_at[close_at.index.hour == 0]
    ret = days / close_at.shift(24).reindex(days.index) - 1
    return np.sign(ret).fillna(0.0)


def backtest(df: pd.DataFrame, tgt: pd.Series, fee: float, period: tuple[str, str]) -> dict:
    """Позиция по решениям, доходность по часам, издержки на изменение позиции,
    фандинг в моменты начисления."""
    r = hourly_returns(df)
    # Позиция на свече с открытием t = последнее решение со временем ≤ t.
    pos = tgt.reindex(r.index.union(tgt.index)).ffill().reindex(r.index).fillna(0.0)
    pnl = pos * r
    change = pos.diff().abs().fillna(pos.abs())
    cost = change * fee
    # Фандинг в момент T платит позиция, которая держалась на свече, закрывающейся в T.
    fund = df["funding"].fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    funding = held * fund
    net = pnl - cost - funding
    a, b = period
    sl = slice(a, b)
    daily = net.loc[sl].resample("1D").sum()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0
    eq = (1 + net.loc[sl]).cumprod()
    dd = float((1 - eq / eq.cummax()).max()) if len(eq) else 0.0
    return {
        "net": float((1 + net.loc[sl]).prod() - 1),
        "gross": float((1 + pnl.loc[sl]).prod() - 1),
        "costs": float(cost.loc[sl].sum()),
        "funding": float(funding.loc[sl].sum()),
        "sharpe": sharpe,
        "trades": int((change.loc[sl] > 0).sum()),
        "exposure": float((pos.loc[sl] != 0).mean()),
        "max_dd": dd,
    }


def main(partial: bool) -> None:
    universe = open(os.path.join(DATA, "universe.txt")).read().split()
    rows = []
    for sym in universe:
        df = pd.read_parquet(os.path.join(DATA, f"{sym}.parquet"))
        cands = {"momentum_4h": targets_momentum(df)}
        pp = os.path.join(DATA, "preds", f"{sym}.parquet")
        if os.path.exists(pp):
            preds = pd.read_parquet(pp)
            if len(preds) >= 2400 or partial:
                cands["kronos_1h"] = targets_kronos(preds)
        for name, tgt in cands.items():
            rows.append({
                "sym": sym, "strategy": name,
                "val": backtest(df, tgt, TAKER, VAL),
                "test": backtest(df, tgt, TAKER, TEST),
                "val_maker": backtest(df, tgt, MAKER, VAL)["net"],
                "test_maker": backtest(df, tgt, MAKER, TEST)["net"],
            })
    missing = [s for s in universe if not any(r["sym"] == s and r["strategy"] == "kronos_1h" for r in rows)]
    if missing and not partial:
        sys.exit(f"нет прогнозов Kronos по {len(missing)} парам: {', '.join(missing)}")

    # Отбор только по валидации.
    passed = [r for r in rows if r["val"]["sharpe"] > RULE["val_sharpe"] and r["val"]["net"] > RULE["val_net"]
              and r["val"]["trades"] >= RULE["val_trades"]]
    best: dict[str, dict] = {}
    for r in sorted(passed, key=lambda r: r["val"]["sharpe"], reverse=True):
        best.setdefault(r["sym"], r)
    chosen = sorted(best.values(), key=lambda r: r["val"]["sharpe"], reverse=True)[: RULE["max_pairs"]]
    # Подтверждение на тесте — один раз.
    for r in chosen:
        r["confirmed"] = r["test"]["net"] > 0 and r["test"]["sharpe"] > 0
    final = [r for r in chosen if r["confirmed"]]

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    report = {
        "version": f"{stamp}-v1" + ("-partial" if partial else ""),
        "rules": RULE, "fees": {"taker": TAKER, "maker_reference": MAKER},
        "periods": {"val": VAL, "test": TEST}, "universe": universe,
        "rows": rows, "chosen_on_val": [(r["sym"], r["strategy"]) for r in chosen],
        "final": [{"sym": r["sym"], "strategy": r["strategy"]} for r in final],
    }
    out = os.path.join(HERE, "report.partial.json" if partial else "report.json")
    with open(out, "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(f"{'пара':14s} {'стратегия':12s} | вал: net    Sharpe сделок | тест: net    Sharpe | мейкер вал/тест")
    for r in sorted(rows, key=lambda r: r["val"]["sharpe"], reverse=True):
        v, t = r["val"], r["test"]
        mark = " ✓" if r in final else (" ✗тест" if r in chosen else "")
        print(f"{r['sym']:14s} {r['strategy']:12s} | {v['net']:+7.1%} {v['sharpe']:+5.2f} {v['trades']:5d} | "
              f"{t['net']:+7.1%} {t['sharpe']:+5.2f} | {r['val_maker']:+6.1%}/{r['test_maker']:+6.1%}{mark}")
    print("\nОтобрано на валидации:", report["chosen_on_val"])
    print("Подтверждено на тесте:", [(r["sym"], r["strategy"]) for r in final])


if __name__ == "__main__":
    main("--partial" in sys.argv)
