import pytest

from app.stats import max_drawdown, rounds_from_fills, summarize


def f(sym, side, qty, price, ts, fee=0.0):
    return {"sym": sym, "side": side, "qty": qty, "price": price, "ts": ts, "fee": fee}


def test_long_round_with_fees():
    r = rounds_from_fills([f("BTC", "buy", 1, 100, 1, 0.1), f("BTC", "sell", 1, 110, 2, 0.1)])
    assert len(r) == 1 and r[0].side == "long" and r[0].pnl == pytest.approx(10)
    assert r[0].net == pytest.approx(9.8)


def test_short_partial_close_and_flip():
    fills = [
        f("ETH", "sell", 2, 50, 1),  # шорт 2
        f("ETH", "buy", 1, 40, 2),  # частично: +10
        f("ETH", "buy", 3, 45, 3),  # закрыл 1 (+5) и перевернулся в лонг 2
        f("ETH", "sell", 2, 47, 4),  # закрыл лонг: +4
    ]
    r = rounds_from_fills(fills)
    assert [x.side for x in r] == ["short", "long"]
    assert r[0].pnl == pytest.approx(15) and r[1].pnl == pytest.approx(4)


def test_open_round_counts_but_not_in_win_rate():
    s = summarize(
        [
            f("A", "buy", 1, 10, 1, 0.01),
            f("A", "sell", 1, 9, 2, 0.01),
            f("B", "buy", 1, 5, 3, 0.01),
        ],
        funding=[0.05],
        equity=[100, 110, 99, 105],
    )
    assert s["rounds_closed"] == 1 and s["rounds_open"] == 1 and s["win_rate"] == 0
    assert s["fees"] == pytest.approx(0.03) and s["funding"] == 0.05
    assert s["net_pnl"] == pytest.approx(-1 - 0.03 - 0.05)
    assert s["max_drawdown"] == pytest.approx(11 / 110)


def test_drawdown_empty_and_monotonic():
    assert max_drawdown([1, 2, 3]) == 0
