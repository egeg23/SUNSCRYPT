"""Сервис сигналов (бриф, этап 4): один на всех.

На закрытии каждой H-й часовой свечи (H=8: 00, 08, 16 UTC) считает прогноз
дообученной Kronos-small по каждой паре один раз и публикует в Redis готовое
решение: rhat (ожидаемая доходность за H свечей), z (rhat минус его среднее за
последние 30 решений, делённое на разброс — «вычитание сдвига прогноза»),
target (+1 / −1 / 0 при |z| > порога). Исполнители кабинетов только следуют
target. Правило выбрано в исследовании заранее (бриф, раздел 2.1).

Запуск: python -m sunscrypt_engine.signal_service
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque

import httpx
import numpy as np
import pandas as pd
import redis

from sunscrypt_engine import keys, market, registry
from sunscrypt_engine import pairs as pairs_cfg

log = logging.getLogger("signals")

CONFIG = pairs_cfg.load()
PAIRS = [p["sym"] for p in CONFIG["pairs"]]
STRATEGY = {p["sym"]: p["strategy"] for p in CONFIG["pairs"]}
MOMENTUM_H = 24  # моментум: раз в сутки (00:00 UTC), знак доходности за 24 часа
BAR_MIN = int(os.environ.get("SIGNAL_BAR_MINUTES", "60"))
H = int(os.environ.get("SIGNAL_HORIZON", "8"))
CONTEXT = 256
Z_WINDOW, Z_MIN, Z_THR = 30, 10, float(os.environ.get("SIGNAL_Z_THRESHOLD", "1.0"))


def decision_bar(ts_close: pd.Timestamp) -> bool:
    """Решение принимается на закрытии каждой H-й свечи (как в исследовании)."""
    return (int(ts_close.value // 60_000_000_000) // BAR_MIN) % H == 0


def zscore(hist: list[float], rhat: float) -> float:
    if len(hist) < Z_MIN:
        return 0.0
    h = np.asarray(hist)
    sd = h.std(ddof=1)
    return float((rhat - h.mean()) / sd) if sd > 0 else 0.0


def target_of(z: float) -> int:
    return int(np.sign(z)) if abs(z) > Z_THR else 0


class Forecaster:
    """Обёртка над быстрым Kronos (engine/sunscrypt_engine/fastkronos.py)."""

    def __init__(self, model_path: str, samples: int = 16):
        import torch

        from sunscrypt_engine.fastkronos import FastKronos, load, prepare

        torch.set_num_threads(int(os.environ.get("KRONOS_THREADS", "2")))
        tok, m, ctx = load("small", model_path)
        self.fk, self.prepare, self.S = FastKronos(tok, m, ctx), prepare, samples

    def rhat(self, df: pd.DataFrame) -> tuple[float, float, float]:
        """df — последние CONTEXT закрытых свечей (индекс — время открытия)."""
        bar = pd.Timedelta(minutes=BAR_MIN)
        fut = pd.date_range(df.index[-1] + bar, periods=H, freq=bar)
        xn, xs, ys, mu, sd = self.prepare(df, df.index, fut)
        z = self.fk.generate(xn[None], xs[None], ys[None], H, S=self.S)
        close = z[0, :, -1, 3] * (sd[3] + 1e-5) + mu[3]
        r = close / df["close"].iloc[-1] - 1
        return float(r.mean()), float((r > 0).mean()), float(r.std())


def weights_ready(version: str) -> bool:
    return os.path.exists(os.path.join(registry.path_of(version), "model.safetensors"))


class SignalService:
    def __init__(self, r: redis.Redis, forecaster, fetch=market.klines, version: str = registry.BASE,
                 make_forecaster=None):
        self.r, self.fc, self.fetch, self.version = r, forecaster, fetch, version
        self.make_forecaster = make_forecaster or (lambda v: Forecaster(registry.path_of(v)))

    def sync_champion(self) -> None:
        """Выпущена или откачена версия модели (этап 8) — переходим на неё.
        История прогнозов для z-оценки — от старой модели, её прогнозы в
        другой шкале: стираем, backfill посчитает заново новой моделью."""
        v = registry.champion()
        if v == self.version or not weights_ready(v):
            return
        log.info("модель: %s → %s", self.version, v)
        self.fc, self.version = self.make_forecaster(v), v
        for sym in PAIRS:
            if STRATEGY.get(sym) != "momentum_4h":
                self.r.delete(keys.ZHIST.format(sym=sym))

    def _hist(self, sym: str) -> list[dict]:
        return [json.loads(x) for x in self.r.lrange(keys.ZHIST.format(sym=sym), 0, -1)]

    def backfill(self, sym: str, df: pd.DataFrame) -> None:
        """Первый запуск: история прогнозов за последние Z_WINDOW решений, чтобы
        z-оценка работала сразу, а не через 10 решений (80 часов)."""
        if self.r.llen(keys.ZHIST.format(sym=sym)) >= Z_MIN:
            return
        bar = pd.Timedelta(minutes=BAR_MIN)
        closes = [t + bar for t in df.index]
        points = [i for i, t in enumerate(closes) if decision_bar(t) and i >= CONTEXT - 1]
        for i in points[-Z_WINDOW - 1 : -1]:
            rh = self.fc.rhat(df.iloc[i - CONTEXT + 1 : i + 1])[0]
            self._push(sym, int(closes[i].value // 1_000_000), rh)
        log.info("%s: история прогнозов восстановлена (%d)", sym, len(points[-Z_WINDOW - 1 : -1]))

    def _push(self, sym: str, ts_ms: int, rhat: float) -> None:
        k = keys.ZHIST.format(sym=sym)
        self.r.rpush(k, json.dumps({"ts": ts_ms, "rhat": rhat}))
        self.r.ltrim(k, -Z_WINDOW, -1)

    def step(self, sym: str, now: float | None = None) -> dict | None:
        if STRATEGY.get(sym, "kronos_1h") == "momentum_4h":
            return self.step_momentum(sym, now)
        return self.step_kronos(sym, now)

    def _publish(self, sig: dict) -> dict:
        self.r.set(keys.SIGNAL.format(sym=sig["sym"]), json.dumps(sig))
        self.r.xadd(keys.SIGNAL_STREAM, {"json": json.dumps(sig)}, maxlen=20000, approximate=True)
        log.info("%s: %s rhat=%+.4f z=%+.2f → %+d", sig["sym"], sig["model"], sig["rhat"], sig["z"], sig["target"])
        return sig

    def step_momentum(self, sym: str, now: float | None = None) -> dict | None:
        """Моментум без модели (бриф, кандидат этапа 7): раз в сутки позиция =
        знак доходности за последние 24 часа, всегда в рынке."""
        period_ms = MOMENTUM_H * BAR_MIN * 60_000
        due_ms = int((now if now is not None else time.time()) * 1000) // period_ms * period_ms
        last = self.r.get(keys.SIGNAL.format(sym=sym))
        if last and json.loads(last)["ts_close"] >= due_ms:
            return None
        df = self.fetch(sym, BAR_MIN, 200)
        bar = pd.Timedelta(minutes=BAR_MIN)
        df = df[df.index + bar <= pd.Timestamp(due_ms, unit="ms")]
        if len(df) <= MOMENTUM_H or int((df.index[-1] + bar).value // 1_000_000) != due_ms:
            return None
        ret = float(df["close"].iloc[-1] / df["close"].iloc[-1 - MOMENTUM_H] - 1)
        paused = self.r.get(keys.PAUSE_PAIR.format(sym=sym))
        return self._publish({
            "sym": sym, "ts_close": due_ms, "bar_minutes": BAR_MIN, "horizon": MOMENTUM_H,
            "close": float(df["close"].iloc[-1]), "rhat": ret, "pup": float(ret > 0), "sd": 0.0,
            "z": 0.0, "target": 0 if paused else int(np.sign(ret)), "model": "momentum_4h",
            "paused": bool(paused),
            "created_at": int(time.time() * 1000),
        })

    def step_kronos(self, sym: str, now: float | None = None) -> dict | None:
        """Новое решение по паре, если закрылась решающая свеча и его ещё нет."""
        period_ms = H * BAR_MIN * 60_000
        due_ms = int((now if now is not None else time.time()) * 1000) // period_ms * period_ms
        last = self.r.get(keys.SIGNAL.format(sym=sym))
        if last and json.loads(last)["ts_close"] >= due_ms:
            return None  # решение по последнему окну уже есть — свечи не нужны
        df = self.fetch(sym, BAR_MIN, 1000)
        # Решение по текущему окну — на свечах ровно до его начала: так же,
        # как если бы сервис работал в момент закрытия решающей свечи (после
        # перезапуска посреди окна не надо ждать следующего).
        bar = pd.Timedelta(minutes=BAR_MIN)
        df = df[df.index + bar <= pd.Timestamp(due_ms, unit="ms")]
        if len(df) < CONTEXT:
            return None
        ts_close = df.index[-1] + bar
        ts_ms = int(ts_close.value // 1_000_000)
        if ts_ms != due_ms or not decision_bar(ts_close):
            return None  # свечи до начала окна ещё не пришли
        self.backfill(sym, df.iloc[:-1])
        rhat, pup, sd = self.fc.rhat(df.iloc[-CONTEXT:])
        hist = [h["rhat"] for h in self._hist(sym) if h["ts"] < ts_ms]
        z = zscore(hist[-Z_WINDOW:], rhat)
        paused = self.r.get(keys.PAUSE_KRONOS) or self.r.get(keys.PAUSE_PAIR.format(sym=sym))
        sig = {
            "sym": sym,
            "ts_close": ts_ms,
            "bar_minutes": BAR_MIN,
            "horizon": H,
            "close": float(df["close"].iloc[-1]),
            "rhat": rhat,
            "pup": pup,
            "sd": sd,
            "z": z,
            # Пауза контроля дрейфа: прогноз считаем (для истории), в рынок не идём.
            "target": 0 if paused else target_of(z),
            "model": self.version,
            "paused": bool(paused),
            "created_at": int(time.time() * 1000),
        }
        self._push(sym, ts_ms, rhat)
        return self._publish(sig)

    def loop(self) -> None:
        client = httpx.Client(timeout=20)
        fetch = self.fetch
        self.fetch = lambda s, m, n: fetch(s, m, n, client)
        while True:
            self.sync_champion()
            for sym in PAIRS:
                try:
                    self.step(sym)
                except (httpx.HTTPError, RuntimeError) as e:
                    log.warning("%s: свечи не получены: %s", sym, e)
                except Exception:
                    log.exception("%s: сигнал не посчитан", sym)
                # Bybit ограничивает частоту запросов с одного IP: не всё разом.
                time.sleep(0.5)
            self.r.set(keys.HB_SIGNALS, json.dumps({"ts": int(time.time() * 1000), "pairs": PAIRS,
                                                    "config": CONFIG["version"], "model": self.version}), ex=600)
            # Свеча закрывается в начале часа; Bybit отдаёт её через секунды.
            time.sleep(30)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    version = registry.champion()
    while not weights_ready(version):
        # Веса кладёт выкатка (infra/deploy.sh); без них — ждём, а не падаем.
        log.warning("нет весов модели %s — жду", version)
        r.set(keys.HB_SIGNALS, json.dumps({"ts": int(time.time() * 1000), "pairs": [], "waiting": "weights"}), ex=600)
        time.sleep(60)
        version = registry.champion()
    SignalService(r, Forecaster(registry.path_of(version)), version=version).loop()


if __name__ == "__main__":
    main()
