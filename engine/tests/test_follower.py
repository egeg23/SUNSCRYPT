"""Исполнитель на бэктест-движке Nautilus: следует сигналам из Redis,
переворачивается, закрывает всё по аварийной остановке, держит плечо."""

import json
import os
import sys
from decimal import Decimal

import fakeredis
import numpy as np
import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    BookType,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TraderId,
    Venue,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sunscrypt_engine import keys  # noqa: E402
from sunscrypt_engine.follower import FollowerConfig, FollowerStrategy  # noqa: E402

IID = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
MIN = 60_000_000_000
T0 = 1_790_000_000_000_000_000 // (8 * 60 * MIN) * (8 * 60 * MIN)  # начало 8-часового окна


def instrument():
    usdt = Currency.from_str("USDT")
    return CryptoPerpetual(
        instrument_id=IID, raw_symbol=Symbol("BTCUSDT"), base_currency=Currency.from_str("BTC"),
        quote_currency=usdt, settlement_currency=usdt, is_inverse=False, price_precision=1,
        size_precision=3, price_increment=Price(0.1, 1), size_increment=Quantity(0.001, 3),
        ts_event=0, ts_init=0, margin_init=Decimal("0.1"), margin_maint=Decimal("0.05"),
    )


def quotes(minutes: int):
    rng = np.random.default_rng(1)
    px = 80_000 + np.cumsum(rng.normal(0, 20, minutes))
    return [
        QuoteTick(IID, Price(p - 0.5, 1), Price(p + 0.5, 1), Quantity(5, 3), Quantity(5, 3),
                  T0 + i * MIN, T0 + i * MIN)
        for i, p in enumerate(px)
    ]


def signal(r, ts_min: int, target: int):
    r.set(keys.SIGNAL.format(sym="BTCUSDT"), json.dumps({
        "sym": "BTCUSDT", "ts_close": (T0 + ts_min * MIN) // 1_000_000, "bar_minutes": 60,
        "horizon": 8, "target": target, "rhat": 0.01 * target, "z": 1.5 * target,
    }))


class Scripted(FollowerStrategy):
    """Сценарий: по минутам меняет сигнал и флаги в Redis."""

    script: dict[int, callable] = {}
    seen: list[tuple[int, float]] = []

    def _tick(self, event=None):
        minute = (self.clock.timestamp_ns() - T0) // MIN
        for m in [m for m in self.script if m <= minute]:
            self.script.pop(m)(self.r)
        super()._tick(event)
        self.seen.append((minute, float(self.portfolio.net_position(IID))))


@pytest.fixture
def run():
    def _run(script, minutes=240, leverage=1.0, execution="maker", daily_loss_pct=50, r=None):
        r = r if r is not None else fakeredis.FakeRedis()
        Scripted.script, Scripted.seen = dict(script), []
        engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId("BT-001")))
        engine.add_venue(venue=Venue("BYBIT"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                         base_currency=None, starting_balances=[Money(100_000, Currency.from_str("USDT"))],
                         book_type=BookType.L1_MBP,
                         fee_model=MakerTakerFeeModel(maker_rate=Decimal("0.0002"), taker_rate=Decimal("0.00055")))
        engine.add_instrument(instrument())
        engine.add_data(quotes(minutes))
        engine.add_strategy(Scripted(FollowerConfig(
            account_id="a1", instrument_ids=[IID], redis=r, capital_usd=10_000,
            leverage=leverage, daily_loss_pct=daily_loss_pct, execution=execution)))
        engine.run()
        seen = list(Scripted.seen)
        engine.dispose()
        return r, seen
    return _run


def pos_at(seen, minute):
    return [p for m, p in seen if m <= minute][-1]


def test_follows_long_then_short_then_emergency_stop(run):
    r, seen = run({
        1: lambda r: signal(r, 0, +1),
        60: lambda r: signal(r, 60, -1),
        150: lambda r: r.set(keys.STOP_ACCOUNT.format(id="a1"), "1"),
    })
    assert pos_at(seen, 55) == pytest.approx(10_000 / 80_000, abs=0.01)  # ≈ 0.125 BTC в лонг
    assert pos_at(seen, 140) == pytest.approx(-10_000 / 80_000, abs=0.01)  # перевернулся в шорт
    assert pos_at(seen, 170) == 0  # аварийная остановка — всё закрыто
    hb = json.loads(r.get(keys.HB_ACCOUNT.format(id="a1")))
    assert hb["halted"] == "кабинет остановлен" and hb["positions"] == {}
    fills = r.xrange(keys.FILLS.format(id="a1"))
    assert len(fills) >= 3 and all(f[1][b"price"] for f in fills)


def test_flat_signal_and_stale_signal(run):
    _, seen = run({1: lambda r: signal(r, 0, 0)}, minutes=60)
    assert all(p == 0 for _, p in seen)
    # Сигнал старше H+1 свечей не исполняется.
    _, seen = run({1: lambda r: signal(r, -10 * 60, +1)}, minutes=60)
    assert all(p == 0 for _, p in seen)


def test_leverage_two_doubles_size_and_three_is_refused(run):
    _, seen = run({1: lambda r: signal(r, 0, +1)}, minutes=60, leverage=2.0)
    assert pos_at(seen, 55) == pytest.approx(2 * 10_000 / 80_000, abs=0.02)
    with pytest.raises(ValueError):
        FollowerConfig(account_id="x", instrument_ids=[IID], redis=None, capital_usd=1, leverage=3)


def test_global_stop(run):
    _, seen = run({1: lambda r: signal(r, 0, +1), 40: lambda r: r.set(keys.STOP_GLOBAL, "1")}, minutes=80)
    assert pos_at(seen, 30) > 0 and pos_at(seen, 70) == 0


def test_daily_loss_halt_survives_restart(run):
    # Лимит 0.01 % от 10 000 = 1 USD: первая же комиссия (≈2 USD) его съедает.
    r, seen = run({1: lambda r: signal(r, 0, +1)}, minutes=60, daily_loss_pct=0.01)
    assert max(p for _, p in seen) > 0 and seen[-1][1] == 0  # вошёл, лимит — вышел
    day = [k for k in r.keys("dayhalt:*")]
    assert day and "дневной лимит" in r.get(day[0]).decode()
    # «Перезапуск» в те же сутки: новый процесс, та же Redis — стоит.
    _, seen2 = run({1: lambda r: signal(r, 0, +1)}, minutes=60, daily_loss_pct=0.01, r=r)
    assert all(p == 0 for _, p in seen2)
