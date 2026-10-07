"""Оценка стратегии на истории после комиссий — та же арифметика, что в
отборе пар (research/selection/evaluate.py, правила RULES.md), для
дообучения и контроля дрейфа (этап 8).

Решение Kronos: z-оценка прогноза относительно 30 прошлых прогнозов той же
модели, позиция ±1 при |z| > 1, иначе вне рынка — как в сервисе сигналов.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TAKER = 0.00075  # комиссия Bybit за рыночный ордер (худший случай)
Z_WINDOW, Z_MIN, Z_THR = 30, 10, 1.0


def targets_kronos(rhat: pd.Series) -> pd.Series:
    """Решения во время закрытия решающей свечи (индекс — это время)."""
    rh = rhat.to_numpy()
    out = np.zeros(len(rh))
    for i in range(len(rh)):
        hist = rh[max(0, i - Z_WINDOW) : i]
        if len(hist) < Z_MIN:
            continue
        sd = hist.std(ddof=1)
        z = (rh[i] - hist.mean()) / sd if sd > 0 else 0.0
        out[i] = np.sign(z) if abs(z) > Z_THR else 0.0
    return pd.Series(out, index=rhat.index)


def targets_momentum(df: pd.DataFrame) -> pd.Series:
    """Простая база: раз в сутки (00:00 UTC) знак доходности за 24 часа."""
    close_at = df["close"].copy()
    close_at.index = close_at.index + pd.Timedelta(hours=1)  # время закрытия
    days = close_at[close_at.index.hour == 0]
    ret = days / close_at.shift(24).reindex(days.index) - 1
    return np.sign(ret).fillna(0.0)


def net_series(df: pd.DataFrame, tgt: pd.Series, fee: float = TAKER) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Почасовой результат после комиссии и фандинга; позиция; её изменения."""
    r = df["close"].pct_change().fillna(0.0)
    pos = tgt.reindex(r.index.union(tgt.index)).ffill().reindex(r.index).fillna(0.0)
    change = pos.diff().abs().fillna(pos.abs())
    fund = df["funding"].fillna(0.0) if "funding" in df else pd.Series(0.0, index=df.index)
    return pos * r - change * fee - pos.shift(1).fillna(0.0) * fund, pos, change


def backtest(df: pd.DataFrame, tgt: pd.Series, period: tuple, fee: float = TAKER) -> dict:
    """Позиция по решениям, доходность по часовым свечам (индекс — время
    открытия), комиссия на изменение позиции, фандинг (если есть колонка)."""
    net, pos, change = net_series(df, tgt, fee)
    a, b = period
    seg = net.loc[a:b]
    daily = seg.resample("1D").sum()
    sd = daily.std()
    return {
        "net": float((1 + seg).prod() - 1),
        "sharpe": float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0,
        "trades": int((change.loc[a:b] > 0).sum()),
        "exposure": float((pos.loc[a:b] != 0).mean()) if len(seg) else 0.0,
        # Для контроля дрейфа: результат за каждое 8-часовое окно решения.
        "per_window_mean": float(seg.resample("8h").sum().mean()) if len(seg) else 0.0,
        "per_window_sd": float(seg.resample("8h").sum().std()) if len(seg) > 16 else 0.0,
    }


def mean_of(rows: dict[str, dict], field: str = "net") -> float:
    """Среднее по парам (равные доли капитала)."""
    return float(np.mean([v[field] for v in rows.values()])) if rows else 0.0


def decide(champion: float, challenger: float, baseline: float) -> tuple[bool, str]:
    """Правило выпуска (бриф, этап 8): претендент выходит, только если после
    комиссий лучше чемпиона и лучше простых баз (моментум и «не торговать»)."""
    bar = max(baseline, 0.0)
    nums = (
        f"претендент {challenger:+.2%}, чемпион {champion:+.2%}, "
        f"моментум {baseline:+.2%}, без торговли 0%"
    )
    if challenger <= champion:
        return False, f"Не лучше чемпиона: {nums}"
    if challenger <= bar:
        return False, f"Не лучше простых баз: {nums}"
    return True, f"Лучше чемпиона и простых баз: {nums}"


def drift(live: list[float], exp_mean: float, exp_sd: float, min_n: int = 45, k: float = 3.0) -> tuple[bool, str]:
    """Живые результаты окон решений против ожидания из проверки на истории:
    дрейф, если среднее ниже ожидаемого больше чем на k стандартных ошибок."""
    n = len(live)
    if n < min_n or exp_sd <= 0:
        return False, f"Мало данных для контроля дрейфа: окон {n} из {min_n}"
    m = float(np.mean(live))
    se = exp_sd / np.sqrt(n)
    z = (m - exp_mean) / se
    text = f"живые окна: {n}, среднее {m:+.3%} против ожидаемого {exp_mean:+.3%} (z = {z:+.1f})"
    return z < -k, ("Дрейф: " if z < -k else "Без дрейфа: ") + text
