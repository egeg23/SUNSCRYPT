"""Этап 8: правило выпуска, контроль дрейфа, живые окна сигналов."""

import json
import os
import sys

import fakeredis
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sunscrypt_engine import evalkit, keys, models_job  # noqa: E402


def test_release_only_if_better_than_champion_and_baselines():
    assert evalkit.decide(0.01, 0.02, -0.05)[0]
    ok, why = evalkit.decide(0.03, 0.02, -0.05)
    assert not ok and "чемпиона" in why
    ok, why = evalkit.decide(-0.05, -0.03, -0.14)  # лучше чемпиона, но хуже «не торговать»
    assert not ok and "баз" in why
    assert not evalkit.decide(0.01, 0.02, 0.03)[0]  # моментум лучше


def test_drift_needs_enough_windows_and_clear_shortfall():
    assert not evalkit.drift([-0.01] * 10, 0.001, 0.01)[0]  # мало данных
    assert not evalkit.drift([0.0005] * 60, 0.001, 0.01)[0]  # в пределах разброса
    bad, why = evalkit.drift([-0.01] * 60, 0.001, 0.01)
    assert bad and why.startswith("Дрейф")


def _sig(sym, h, close, target, model="v1", paused=False):
    return {"json": json.dumps({"sym": sym, "ts_close": h * 3_600_000, "close": close, "target": target,
                                "model": model, "paused": paused})}


def test_live_windows_net_of_fees_per_pair():
    r = fakeredis.FakeRedis()
    for f in [_sig("BTCUSDT", 0, 100, 1), _sig("BTCUSDT", 8, 110, -1), _sig("BTCUSDT", 16, 99, 0),
              _sig("ETHUSDT", 0, 10, 1, model="old"), _sig("BTCUSDT", 32, 50, 1)]:
        r.xadd(keys.SIGNAL_STREAM, f)
    w = models_job.live_windows(r, "v1", 0)
    fee = evalkit.TAKER
    # 0→8: лонг +10% минус вход; 8→16: шорт −(99/110−1) минус разворот (2 стороны);
    # 16→32 — пропуск окна (разрыв), чужая модель — не считается.
    assert w == pytest.approx([0.1 - fee, -1 * (99 / 110 - 1) - 2 * fee])


def test_pair_drift_pauses_only_the_broken_pair(monkeypatch):
    r = fakeredis.FakeRedis()
    exp = {"window_h": 24, "mean": 0.002, "sd": 0.04}
    monkeypatch.setattr(models_job.pairs_cfg, "load", lambda: {"pairs": [
        {"sym": "AAAUSDT", "strategy": "momentum_4h", "expect": exp},
        {"sym": "BBBUSDT", "strategy": "momentum_4h", "expect": exp}]})
    recorded = []
    monkeypatch.setattr(models_job, "record", lambda *a, **k: recorded.append(a))
    price = {"AAAUSDT": 100.0, "BBBUSDT": 100.0}
    for day in range(30):
        for sym, move in (("AAAUSDT", 0.97), ("BBBUSDT", 1.001)):  # A: −3% каждый день в лонге
            r.xadd(keys.SIGNAL_STREAM, {"json": json.dumps({
                "sym": sym, "ts_close": day * 86_400_000, "close": price[sym], "target": 1,
                "model": "momentum_4h", "paused": False})})
            price[sym] *= move
    out = models_job.check_pairs_drift(r)
    assert r.get(keys.PAUSE_PAIR.format(sym="AAAUSDT")) and not r.get(keys.PAUSE_PAIR.format(sym="BBBUSDT"))
    assert out[0].startswith("AAAUSDT: Дрейф") and "Без дрейфа" in out[1]
    assert recorded and recorded[0][1] == "paused"
