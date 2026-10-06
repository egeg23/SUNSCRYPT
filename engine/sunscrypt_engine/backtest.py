"""Backtest KronosStrategy on the NautilusTrader engine (Bybit fees, netting, margin account).

  python nt/backtest.py --tf 1h --signals replay --tag ft300 --execution taker
Bars: Binance USDT-M perp candles (Bybit REST is geo-blocked in the research container), test period.
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

import numpy as np
import pandas as pd

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (AccountType, Bar, BarType, CryptoPerpetual, Currency, InstrumentId, Money,
                                   OmsType, Price, Quantity, Symbol, TraderId, Venue)

sys.path.insert(0, os.path.dirname(__file__))
from signals import KronosSignals, MomentumSignals, ReplaySignals  # noqa: E402
from strategy import KronosStrategy, KronosStrategyConfig  # noqa: E402

from paths import DATA_DIR, MODEL_DIR, RESULTS_DIR  # noqa: E402
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
TF = {"1h": (60, 8, "1-HOUR"), "4h": (240, 6, "4-HOUR")}
# Bybit linear perp size steps (price precision is taken from the data)
SIZE_STEP = {"BTCUSDT": "0.001", "ETHUSDT": "0.01", "SOLUSDT": "0.1", "XRPUSDT": "1", "BNBUSDT": "0.01", "ADAUSDT": "1"}
VENUE = Venue("BYBIT")


def price_precision(x: np.ndarray) -> int:
    s = pd.Series(x[:2000]).map(lambda v: f"{v:.8f}".rstrip("0").split(".")[1] if "." in f"{v:.8f}".rstrip("0") else "")
    return int(s.str.len().max())


def make_instrument(sym, pp):
    usdt = Currency.from_str("USDT")
    step = SIZE_STEP[sym]
    sp = len(step.split(".")[1]) if "." in step else 0
    return CryptoPerpetual(
        instrument_id=InstrumentId.from_str(f"{sym}-LINEAR.BYBIT"), raw_symbol=Symbol(sym),
        base_currency=Currency.from_str(sym[:-4]), quote_currency=usdt, settlement_currency=usdt, is_inverse=False,
        price_precision=pp, size_precision=sp, price_increment=Price(10 ** -pp, pp),
        size_increment=Quantity(float(step), sp), ts_event=0, ts_init=0,
        margin_init=Decimal("0.1"), margin_maint=Decimal("0.05"))


def make_bars(inst, bar_type, df, bar_min):
    pp, sp = inst.price_precision, inst.size_precision
    out = []
    close_ns = (df.index + pd.Timedelta(minutes=bar_min)).values.astype("datetime64[ns]").astype("int64")
    for (o, h, l, c, v), ts in zip(df[["open", "high", "low", "close", "volume"]].values, close_ns):
        out.append(Bar(bar_type, Price(o, pp), Price(h, pp), Price(l, pp), Price(c, pp),
                       Quantity(round(v, sp), sp), int(ts), int(ts)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--signals", default="replay", choices=["replay", "kronos", "momentum"])
    ap.add_argument("--tag", default="ft300")
    ap.add_argument("--model_path", default=MODEL_DIR)
    ap.add_argument("--execution", default="taker", choices=["taker", "maker"])
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-10-01")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--notional", type=float, default=10_000.0)
    ap.add_argument("--slippage_bps", type=float, default=2.0, help="added to the taker fee (research used 2 bp/side)")
    a = ap.parse_args()
    bar_min, H, spec = TF[a.tf]
    syms = a.symbols.split(",")

    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("KRONOS-BT-001"),
                                                 risk_engine=RiskEngineConfig(bypass=False), bypass_logging=True))
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=None,
                     starting_balances=[Money(6 * a.notional, Currency.from_str("USDT"))],
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal("0.0002"),
                                                  taker_rate=Decimal("0.00055") + Decimal(str(a.slippage_bps)) / 10_000))
    iids, bts = [], []
    warm = pd.Timedelta(minutes=bar_min * 300)
    for s in syms:
        df = pd.read_parquet(f"{DATA_DIR}/binance/{s}_{a.tf}.parquet")
        df = df.loc[pd.Timestamp(a.start) - (pd.Timedelta(0) if a.signals == "replay" else warm):a.end]
        inst = make_instrument(s, price_precision(df["close"].values))
        engine.add_instrument(inst)
        bt = BarType.from_str(f"{inst.id}-{spec}-LAST-EXTERNAL")
        engine.add_data(make_bars(inst, bt, df, bar_min))
        iids.append(inst.id); bts.append(bt)
    if a.signals == "replay":
        src = ReplaySignals(a.tag, "test", a.tf, syms, bar_min)
    elif a.signals == "momentum":
        src = MomentumSignals(H)
    else:
        src = KronosSignals(model_path=a.model_path, horizon=H, bar_minutes=bar_min)
    strat = KronosStrategy(KronosStrategyConfig(instrument_ids=iids, bar_types=bts, signal_source=src, horizon=H,
                                                bar_minutes=bar_min, notional_usd=a.notional, execution=a.execution,
                                                use_z=(a.signals != "momentum"),
                                                trade_after_ns=int(pd.Timestamp(a.start).value),
                                                max_daily_loss_usd=1e12, kill_file="__no_kill_in_backtest__"))
    engine.add_strategy(strat)
    engine.run()

    acct = engine.generate_account_report(VENUE)
    fills = engine.generate_order_fills_report()
    pos = engine.generate_positions_report()
    os.makedirs(f"{RESULTS_DIR}/nautilus", exist_ok=True)
    tag = f"{a.tf}_{a.signals}_{a.execution}"
    acct.to_csv(f"{RESULTS_DIR}/nautilus/account_{tag}.csv"); fills.to_csv(f"{RESULTS_DIR}/nautilus/fills_{tag}.csv")
    bal = acct["total"].astype(float)
    bal.index = pd.to_datetime(bal.index)
    daily = bal.resample("1D").last().ffill()
    ret = daily.pct_change().dropna()
    start_cap = 6 * a.notional
    print(f"[{tag}] fills={len(fills)} positions={len(pos)} decisions={len(strat.decisions)}")
    print(f"[{tag}] final balance {bal.iloc[-1]:.2f} from {start_cap:.0f} -> {bal.iloc[-1] / start_cap - 1:+.2%}; "
          f"daily Sharpe {ret.mean() / ret.std() * np.sqrt(365):.2f}; max DD {(daily / daily.cummax() - 1).min():.2%}")
    engine.reset(); engine.dispose()


if __name__ == "__main__":
    main()
