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
    # Свеча, закрывающая окно, ещё не пришла — решения нет.
    assert service(bars("2026-10-06 15:00")).step("BTCUSDT", at("2026-10-06 16:00:30")) is None


def test_restart_mid_window_uses_bars_up_to_window_start():
    svc = service(bars("2026-10-06 22:00"))
    sig = svc.step("BTCUSDT", at("2026-10-06 22:23"))
    assert sig["ts_close"] == int(pd.Timestamp("2026-10-06 16:00").value // 1_000_000)


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


def test_momentum_daily_sign_of_24h_return(monkeypatch):
    monkeypatch.setitem(ss.STRATEGY, "DOGEUSDT", "momentum_4h")
    df = bars("2026-10-07 00:00", n=100)
    svc = service(df)
    sig = svc.step("DOGEUSDT", at("2026-10-07 03:00"))
    expect = np.sign(df["close"].iloc[-1] / df["close"].iloc[-25] - 1)
    assert sig["model"] == "momentum_4h" and sig["target"] == expect and sig["horizon"] == 24
    assert svc.step("DOGEUSDT", at("2026-10-07 20:00")) is None  # раз в сутки


def test_switches_to_new_champion_and_resets_z_history(tmp_path, monkeypatch):
    from sunscrypt_engine import registry

    monkeypatch.setattr(registry, "ROOT", str(tmp_path))
    monkeypatch.setattr(ss, "PAIRS", ["BTCUSDT"])  # не зависеть от боевого конфига пар
    monkeypatch.setattr(ss, "STRATEGY", {"BTCUSDT": "kronos_1h"})
    (tmp_path / "registry" / "v2").mkdir(parents=True)
    (tmp_path / "registry" / "v2" / "model.safetensors").write_bytes(b"x")
    made = []
    svc = ss.SignalService(fakeredis.FakeRedis(), StubModel(), fetch=lambda s, m, n: bars("2026-10-06 16:00"),
                           make_forecaster=lambda v: made.append(v) or StubModel())
    svc.step("BTCUSDT", at("2026-10-06 16:00:30"))
    assert svc.r.llen(keys.ZHIST.format(sym="BTCUSDT")) > 0
    svc.fetch = lambda s, m, n: bars("2026-10-07 00:00")
    svc.sync_champion()
    assert made == [] and svc.version == registry.BASE  # указателя нет — исходная модель
    registry.set_champion("v2")
    svc.sync_champion()
    assert made == ["v2"] and svc.version == "v2"
    assert svc.r.llen(keys.ZHIST.format(sym="BTCUSDT")) == 0
    sig = svc.step("BTCUSDT", at("2026-10-07 00:00:30"))
    assert sig["model"] == "v2"


def test_pause_keeps_forecast_but_stays_flat():
    svc = service(bars("2026-10-06 16:00"))
    svc.r.set(keys.PAUSE_KRONOS, "дрейф")
    sig = svc.step("BTCUSDT", at("2026-10-06 16:00:30"))
    assert sig["paused"] and sig["target"] == 0 and sig["rhat"] != 0


def test_switch_kronos_to_momentum_decides_same_window(monkeypatch):
    # В окне уже лежит сигнал Kronos — моментум всё равно решает (а не ждёт сутки).
    monkeypatch.setattr(ss, "STRATEGY", {"BTCUSDT": "momentum_4h"})
    svc = service(bars("2026-10-07 00:00"))
    svc.r.set(keys.SIGNAL.format(sym="BTCUSDT"), json.dumps({
        "sym": "BTCUSDT", "ts_close": int(pd.Timestamp("2026-10-07 00:00").value // 1_000_000),
        "model": "ft_small_s300", "target": 0}))
    sig = svc.step("BTCUSDT", at("2026-10-07 03:16"))
    assert sig and sig["model"] == "momentum_4h" and sig["target"] in (-1, 1)
    assert svc.step("BTCUSDT", at("2026-10-07 03:17")) is None  # второй раз — нет
