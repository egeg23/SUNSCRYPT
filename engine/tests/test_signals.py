"""Сервис сигналов: решение только на закрытии H-й свечи, одно на свечу,
z-оценка по истории прогнозов (с восстановлением истории при первом
запуске), публикация в Redis. Модель подменена — проверяется логика."""

import json
import os
import sys

import fakeredis
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sunscrypt_engine import keys, signal_service as ss  # noqa: E402


class StubModel:
    def __init__(self):
        self.calls = 0

    def rhat(self, df):
        self.calls += 1
        assert len(df) == ss.CONTEXT
        return float(np.sin(len(df) + df["close"].iloc[-1])) * 0.01, 0.5, 0.01


def bars(end_close: str, n: int = 900) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp(end_close) - pd.Timedelta(hours=1), periods=n, freq="1h")
    c = 80_000 + np.cumsum(np.random.default_rng(0).normal(0, 50, n))
    return pd.DataFrame({"open": c, "high": c + 10, "low": c - 10, "close": c, "volume": 1.0, "amount": c}, index=idx)


def service(df):
    return ss.SignalService(fakeredis.FakeRedis(), StubModel(), fetch=lambda s, m, n: df)


def at(ts: str) -> float:
    return pd.Timestamp(ts).value / 1e9


def test_decision_only_on_hth_bar_close():
    assert ss.decision_bar(pd.Timestamp("2026-10-06 16:00"))
    assert not ss.decision_bar(pd.Timestamp("2026-10-06 17:00"))
    assert service(bars("2026-10-06 17:00")).step("BTCUSDT", at("2026-10-06 17:00:30")) is None


def test_signal_published_once_with_backfilled_z():
    svc = service(bars("2026-10-06 16:00"))
    sig = svc.step("BTCUSDT", at("2026-10-06 16:00:30"))
    assert sig and sig["ts_close"] == int(pd.Timestamp("2026-10-06 16:00").value // 1_000_000)
    assert svc.r.llen(keys.ZHIST.format(sym="BTCUSDT")) == ss.Z_WINDOW  # история + новый
    assert sig["z"] != 0 and sig["target"] in (-1, 0, 1)
    assert sig["target"] == ss.target_of(sig["z"])
    assert json.loads(svc.r.get(keys.SIGNAL.format(sym="BTCUSDT")))["rhat"] == sig["rhat"]
    calls = svc.fc.calls
    # То же окно — ни пересчёта, ни запроса свечей.
    svc.fetch = lambda *a: (_ for _ in ()).throw(AssertionError("лишний запрос свечей"))
    assert svc.step("BTCUSDT", at("2026-10-06 17:30")) is None and svc.fc.calls == calls


def test_zscore_and_target():
    assert ss.zscore([0.0] * 5, 1.0) == 0.0  # мало истории
    hist = list(np.linspace(-0.01, 0.01, 20))
    assert ss.target_of(ss.zscore(hist, 0.05)) == 1
    assert ss.target_of(ss.zscore(hist, -0.05)) == -1
    assert ss.target_of(ss.zscore(hist, 0.0)) == 0
